# Identità della VM replicata

> Dalla 3.22.0. Vale per le VM `qemu` registrate sul nodo di destinazione da
> una replica (job con «Registra VM»). Per i container `lxc` cambia solo
> `onboot`.

## Perché la replica non ha l'uuid della sorgente

Proxmox identifica ogni VM anche con un **uuid SMBIOS** (`smbios1: uuid=…`).
Fino alla 3.21 la registrazione copiava la config della sorgente cambiando
solo nome, storage, CPU e rete: la replica nasceva con lo **stesso uuid** della
produzione.

Veeam Backup for Proxmox usa proprio quell'uuid per riconoscere le VM e, se ne
trova due uguali nel cluster, **esclude la sorgente dal backup**:

```
Warning: The VM 3CX-V20 was excluded from the backup scope:
Another VM in the cluster or node has the same BIOS ID
```

Su un cluster in esercizio (21 settembre 2026) erano fuori backup **12 VM di
produzione**, una per ogni replica registrata, e nessuno lo vedeva: il job
Veeam finiva «con avvisi». Nella stessa config viaggiavano anche `onboot: 1`
(tre repliche sarebbero partite da sole al riavvio del nodo DR, con lo stesso
MAC e IP della produzione) e le sezioni `[snapshot]` della sorgente.

## Cosa scrive la registrazione

| Campo della sorgente | Nella replica | Perché |
|---|---|---|
| `smbios1: uuid=U` | `uuid=uuid5(U, "dapx-replica")`, altri attributi invariati | diverso dalla sorgente e **deterministico**: ri-registrare dà lo stesso valore, Veeam non vede una VM nuova a ogni riconciliazione |
| `smbios1` assente | aggiunto, stabile su `host:vmid` sorgente | Proxmox lo genererebbe al primo start; così non cambia |
| `vmgenid` | derivato dall'uuid della replica | un domain controller Windows avviato in DR vede una generazione diversa |
| `onboot` | sempre `0` | la replica parte solo per decisione umana |
| `netN` (MAC) | **invariato** | continuità di IP al DR; la replica è ferma |
| sezioni `[snapshot]`, `parent:` | rimosse | portano l'uuid e l'onboot della sorgente; un `qm rollback` sulla replica li riporterebbe in vita |
| `description` | `dapx-replica di VM 101 da px-01 \| smbios1 originale: uuid=U \| vmgenid originale: G \| attivazione DR: …` (una eventuale description precedente resta in coda) | l'originale si legge in GUI, senza database |

Gli originali finiscono anche nel job di replica (`sync_jobs.source_smbios_uuid`,
`source_vmgenid`, `replica_smbios_uuid`, su tutti i dischi del gruppo).
La fonte che conta è però la **description**: vale anche per le repliche
corrette a mano prima della 3.22.0 (stessa forma `smbios1 originale: uuid=`),
che nel database non hanno niente.

Il codice: `services/replica_identity.py` (funzioni pure) e
`prepara_config_replica` in `services/proxmox_service.py`, provati da
`tests/test_register_vm_identity.py`.

## Attivare il DR

Quando la sorgente è persa e la replica deve prenderne il posto, i sistemi che
riconoscono la VM dall'uuid (licenze, Veeam, Windows) devono ritrovare quello
originale. Dalla pagina **Virtual Machines → Info** della replica, sezione
«Identità replica»:

1. **Attiva DR…** — chiede di scrivere `ATTIVA`; opzioni: ripristina anche
   `vmgenid` (di norma no), forza anche se la sorgente risulta accesa (di norma
   no).
2. L'appliance chiede al nodo sorgente `qm status`: se la VM è `running` si
   **rifiuta** (409) — due VM con lo stesso uuid nel cluster. Se il nodo
   sorgente non risponde è lo scenario del DR e si procede. Se non c'è un job
   di replica collegato non può verificare: serve «forza».
3. `qm set <vmid> --smbios1 uuid=<originale>` sulla replica, più una nota
   `DR ATTIVATO <data> da <utente>` in coda alla description. Registrato in
   `job_logs` (`activate_dr`) e nell'audit.
4. **La VM non viene avviata.** Lo start resta un'azione separata, dalla
   stessa pagina.

API: `POST /api/vms/node/{node_id}/vm/{vmid}/activate-dr` con
`{"confirm": "ATTIVA", "force": false, "ripristina_vmgenid": false}`
(ruolo operatore). A mano, sul nodo:

```bash
qm config 9101 | grep description     # smbios1 originale: uuid=…
qm set 9101 --smbios1 uuid=<originale>
qm start 9101
```

Per tornare replica dopo il DR (sorgente ricostruita): rimuovere la
registrazione e lasciarla rifare, oppure `qm set 9101 --smbios1
uuid=<derivato>` leggendo il derivato da «UUID attuale» prima dell'attivazione
o dal job (`replica_smbios_uuid`).

## Controllo «UUID duplicati»

Ogni 6 ore lo scheduler legge `smbios1` di tutte le VM dei nodi Proxmox
censiti (`grep -H '^smbios1:' /etc/pve/nodes/*/qemu-server/*.conf`, una
chiamata per nodo: `/etc/pve/nodes/*` è l'intero cluster) e, se due VM
condividono lo stesso uuid, manda un alert `warning` sullo stesso canale di
«replica in ritardo» con le coppie. Cooldown 24 ore per le stesse coppie; una
coppia nuova si segnala subito. Codice: `services/uuid_duplicati.py`,
`SchedulerService._check_uuid_duplicati`.

Conta solo la **prima** riga `smbios1:` di ogni file, cioè la sezione
principale: le sezioni `[snapshot]` che seguono portano l'uuid di quando lo
snapshot fu preso — in una replica registrata prima della 3.22.0 è quello
della sorgente — e Veeam non le guarda (3.23.1, dopo un falso allarme su DTS:
9104 e 9115). Corollario: su una replica registrata prima della 3.22.0 **non
fare `qm rollback`** a uno di quegli snapshot, riporterebbe in vita uuid e
`onboot` della sorgente.

Se l'alert nomina una replica registrata prima della 3.22.0, correggerla a
mano con la stessa forma che scrive il codice:

```bash
python3 -c "import uuid; print(uuid.uuid5(uuid.UUID('<uuid sorgente>'), 'dapx-replica'))"
qm set <vmid replica> --smbios1 uuid=<derivato> --onboot 0 \
  --description "dapx-replica di VM <sorgente> | smbios1 originale: uuid=<uuid sorgente>"
```

## Fuori perimetro

I MAC restano quelli della sorgente (continuità di IP al DR); le VM sorgente
non si toccano; le repliche già corrette a mano non si migrano (sono già nella
forma nuova).
