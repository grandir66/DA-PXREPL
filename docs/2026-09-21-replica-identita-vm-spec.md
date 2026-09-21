# Specifica — Identità della VM replicata: UUID, vmgenid, onboot e attivazione DR

> Per l'agente di sviluppo. Piano in bacheca: `~/.claude/lavori/dapx-replica-uuid.md`.
> Lavorare in questo worktree (`main`), cancello del repo prima di ogni commit,
> rilascio con la checklist dei 7 passi di `CLAUDE.md`. Niente SSH verso DTS.

## 1. Il difetto (misurato su DTS il 2026-09-21)

`ProxmoxService.register_vm` (`backend/services/proxmox_service.py`, ~695-950)
scrive sul nodo di destinazione la config della VM sorgente cambiando solo:
`name`, storage, `cpu` (→ `host`), `bridge`/`tag` delle `netN`, media ottici,
tag `REPL`. **Restano identici**: `smbios1: uuid=…`, `vmgenid`, i MAC delle
`netN`, `onboot`, e vengono copiate anche le sezioni snapshot (`[nome]`).

Conseguenze viste in esercizio:

1. **Veeam Backup for Proxmox** identifica le VM col BIOS UUID e, trovandone
   due uguali, **esclude la sorgente dal backup**:
   `Warning: The VM 3CX-V20 was excluded from the backup scope: Another VM in
   the cluster or node has the same BIOS ID`. Su DTS erano fuori backup
   **12 VM di produzione** (101, 103, 104, 109, 111, 112, 114, 115, 117, 122,
   126, 130), una per ogni replica registrata.
2. **`onboot: 1` ereditato**: tre repliche sarebbero partite da sole al
   riavvio del nodo DR, con lo stesso MAC e lo stesso IP della produzione
   sulle VLAN bridgiate fra le sedi.
3. Le sezioni snapshot copiate portano nome/`onboot`/UUID della sorgente
   dentro la config della replica (rumore, e un `qm rollback` sulla replica
   li riporterebbe in vita).

Correzione fatta a mano su PX-04 il 21/09 (backup
`/root/dapx-replica-conf-bak-20260921-114315`): per ogni replica ferma
`qm set 9xxx --smbios1 uuid=<uuid5(orig,"dapx-replica")> --vmgenid <nuovo>
--onboot 0 --description "dapx-replica di VM N | smbios1 originale: uuid=… |
per attivare il DR: qm set 9xxx --smbios1 uuid=<orig> (poi start)"`.
La registrazione avviene solo se il `.conf` manca sul nodo DR
(`reconcile_pending_vm_registrations`), quindi il fix a mano regge finché una
replica non viene rimossa e ri-registrata: **da qui l'urgenza del codice**.

## 2. Comportamento richiesto

### 2.1 In `register_vm` (config `qemu`; per `lxc` solo `onboot`)

| Campo sorgente | Nella replica | Motivo |
|---|---|---|
| `smbios1: uuid=U[,altro]` | `uuid=uuid5(UUID(U), "dapx-replica")`, gli altri attributi di `smbios1` invariati | diverso dalla sorgente, **deterministico** (ri-registrare dà lo stesso valore, Veeam non vede una VM nuova ogni volta) |
| `smbios1` assente | aggiungere `smbios1: uuid=uuid5(uuid5(NAMESPACE_DAPX, f"{hostname_sorgente}:{vmid}"), "dapx-replica")` | Proxmox lo genera comunque al primo start; meglio stabile |
| `vmgenid: G` | `vmgenid: <uuid4 nuovo>` (o `1` per farlo generare a PVE) | un DC Windows attivato in DR deve vedere un generation id diverso |
| `onboot: 1` | `onboot: 0` sempre; se assente, aggiungere `onboot: 0` | la replica parte solo per decisione umana |
| `netN: …=MAC,…` | **invariato** | continuità di IP al DR; la replica è ferma |
| sezioni `[snapshot]` | **rimosse** (tenere solo la sezione principale; togliere anche `parent:`) | evitano rollback verso config della sorgente |
| `description:` | `dapx-replica di VM {vmid_src} da {host_src} \| smbios1 originale: uuid={U} \| vmgenid originale: {G} \| attivazione DR: ripristinare smbios1 prima dello start` (URL-encoded come fa PVE: `%0A` per a capo) | l'originale resta leggibile da chi apre la VM in GUI, senza database |

Gli originali vanno anche nel DB: nuove colonne sulla tabella delle
registrazioni VM (`source_smbios_uuid`, `source_vmgenid`, `replica_smbios_uuid`),
migrazione in `backend/update_db_schema.py` (stile delle esistenti, es. la
3.16.5 «override registrazione VM»).

### 2.2 Azione «Attiva DR» (rotta + pulsante nella pagina della VM registrata)

`POST /api/vms/{node}/{vmid}/activate-dr` con `confirm: "ATTIVA"`:
1. rifiuta se la VM sorgente risponde ancora (ping/SSH al nodo sorgente e
   `qm status` = running) salvo `force: true`;
2. `qm set {vmid} --smbios1 uuid={source_smbios_uuid}` (+ `--vmgenid {source_vmgenid}` se richiesto dall'utente, default no);
3. **non** avvia la VM: lo start resta un'azione separata e consapevole;
4. scrive un job log con prima/dopo.

### 2.3 Controllo periodico «UUID duplicati»

Nello scheduler (stesso canale degli alert «replica in ritardo»): per ogni
cluster gestito, leggere `smbios1` di tutte le VM (`/etc/pve/nodes/*/qemu-server/*.conf`
via SSH su un nodo, come fa già la cache) e alzare un alert se due VM hanno lo
stesso uuid, con le coppie. Cooldown 24 h come gli altri.

## 3. Prove (cancello)

- `backend/tests/test_register_vm_identity.py` — invarianti, ognuna vista
  **fallire** sul codice attuale prima di tenerla buona:
  1. config con `smbios1: uuid=U` → nella config prodotta l'uuid è ≠ U ed è
     esattamente `uuid5(UUID(U), "dapx-replica")`; chiamare due volte dà lo
     stesso valore;
  2. `vmgenid` ≠ sorgente; `onboot: 0` presente anche se la sorgente non lo ha;
  3. i MAC restano identici; `bridge`/`tag` seguono le regole esistenti;
  4. nessuna sezione `[…]` nella config prodotta, nessun `parent:`;
  5. `description` contiene `smbios1 originale: uuid=U`;
  6. config `lxc`: solo `onboot` cambia.
- Prova del doppio per `activate-dr`: dopo la chiamata la config porta l'uuid
  originale; senza `confirm` → 400; sorgente viva senza `force` → 409.
- Prova del controllo duplicati con tre config finte (due uguali) → un alert
  con la coppia giusta; con uuid tutti diversi → nessun alert.
- Il modo di provare `register_vm` senza SSH: la funzione trasforma
  `config_content` prima di scriverlo; estrarre la trasformazione in una
  funzione pura `prepara_config_replica(config_content, *, vm_type, …) -> (str, warnings)`
  e provare quella (stesso schema di `merge_tag_in_vm_config` in `pve_tags.py`).

## 4. Documentazione e rilascio

- `CHANGELOG.md`: voce con il *perché* (Veeam escludeva le VM di produzione;
  repliche con `onboot` ereditato).
- `docs/`: una pagina «Identità della replica» (perché l'UUID è diverso, come
  si attiva il DR, cosa fa il controllo duplicati); link dal README.
- Versione **minor**; rilascio con i 7 passi (tag + GitHub Release).
- Dopo il rilascio, **installazione su dts-repl in sessione DTS** (con
  Riccardo) e verifica: le 12 repliche non vengono ri-registrate con l'uuid
  vecchio; `activate-dr` provato a secco su una replica di test.

## 5. Fuori scope

Rinominare/derivare i MAC; toccare le VM sorgente; migrare le repliche già
corrette a mano (sono già nel formato nuovo: uuid derivato + description).
