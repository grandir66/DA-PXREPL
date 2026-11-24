# Ritorna all'originale (failback con syncoid) — piano di esecuzione

> Si esegue in linea, in una sessione nuova, i task in ordine. Le caselle tengono il conto.

**Obiettivo:** dopo che una replica è stata accesa al posto dell'originale, riportare la produzione sulla VM originale (stesso VMID, nome, uuid, rete, impostazioni) coi dati aggiornati della replica, e rimettere il job di replica nel verso giusto.
**Architettura:** un servizio nuovo `backend/services/ritorno_originale.py` (logica pura + passi SSH) e tre rotte in `backend/routers/vms.py`, accanto ad «Attiva DR». I dati viaggiano solo con `syncoid_service.run_sync` a ruoli invertiti. La configurazione dell'originale viene fotografata nel DB a ogni corsa del job, perché al momento del ritorno può non esistere più.
**Spec:** richiesta di Riccardo del 24/11/2026 in `TASKS.md` (sezione 2026-11-24) e le quattro risposte qui sotto. Caso reale: 3CX di DTS, fatto a mano il 24/11 (stessa sezione).
**Livello di controllo:** completo (zona rossa: dischi e configurazione di VM di produzione), deciso da Riccardo il 24/11/2026.
**Stato:** approvato · **Ultimo aggiornamento:** 2026-11-24, task 1-4 fatti, fermo prima del task 5

## Decisioni di Riccardo (24/11/2026)

1. **Due tempi**: «Prepara ritorno» a replica accesa, poi «Completa ritorno» con fermo breve.
2. **Accensione automatica con controllo**: il sistema accende l'originale; se non parte, la spegne e riaccende la replica.
3. **Disco vecchio da parte, rinominato**: mai cancellato dal sistema.
4. **Ambito**: VM qemu replicate con syncoid, anche multi-disco (`vm_group_id`). Niente LXC nella prima versione.
5. «Sempre usa syncoid»: niente PBS, niente `zfs send` a mano.

## Vincoli globali

- Nessun `zfs destroy` e nessun `qm destroy` in tutto il servizio. Il disco vecchio si rinomina in `<pool>/dapx-vecchio-<vmid>-<disco>-<AAAAMMGG-HHMM>`: il nome non deve combaciare col modello `vm-<id>-disk-N` di Proxmox, altrimenti resta «di» quella VM e un ripristino forzato lo cancella.
- La replica non si tocca finché l'originale non ha risposto: fino a quel punto il ritorno indietro è `qm start <replica>`.
- Mai due VM accese con lo stesso uuid o lo stesso MAC: «Completa» si rifiuta se la replica non è `stopped` dopo lo spegnimento, e non accende l'originale se la replica è `running`.
- Al ritorno si rimettono i valori **dell'originale**, non quelli della replica: `name`, `netN` (bridge e tag VLAN), `onboot`, `tags`, `smbios1`, `vmgenid`, `description`. Incidente DTS 24/11: la 103 partita su `vmbr1` (bridge della replica, senza porte su DTS-PX-UP) è rimasta isolata 3 minuti.
- Rotte con `require_operator`, `check_node_access` sui due nodi, parola di conferma `RITORNA`, `JobLog` (`job_type="ritorno_prepara"` / `"ritorno_completa"`) e `log_audit`.
- Comandi SSH con `shlex.quote`, VMID passati con `int()`, dataset validati con `_assert_dataset` di `syncoid_service`.
- Un ritorno per VM alla volta: stato tenuto nel DB, non in memoria (il servizio può riavviarsi a metà).
- Zona gialla toccata: `backend/database.py` e `backend/update_db_schema.py` (solo colonne nuove, con `_ensure_column`).

| ID | Stato | Passo | Agente | Dipende da | Fatto quando | Verifica |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | [x] | Fotografia della configurazione dell'originale a ogni corsa | in linea | — | la colonna si riempie dopo una corsa | pytest del task 1 |
| S2 | [x] | Logica pura del ritorno (piano dei passi, conf ricostruita, nomi) | in linea | S1 | le prove passano dopo essere state viste fallire | pytest del task 2 |
| S3 | [x] | Passi SSH e rotte «stato», «prepara», «completa» | in linea | S2 | le rotte rispondono e rifiutano i casi vietati | pytest del task 3 |
| S4 | [x] | Interfaccia in `VMs.vue` | in linea | S3 | lint e build puliti, una schermata a 1920 | `npm run lint`, `npm run build:check` |
| S5 | [x] | Prova vera su una VM di test a Domarc | in linea | S4 | ritorno riuscito e ritorno fallito apposta, tutti e due letti | registro del piano |
| S6 | [x] | Documenti e rilascio | in linea | S5 | release su GitHub | `gh release view` |

## Casi da non dimenticare

1. L'originale non esiste più sul nodo (conf sparita): si ricrea dalla fotografia. — Task 2 e 5.
2. Il disco dell'originale esiste ma è danneggiato o ha camminato: nessuno snapshot in comune, quindi copia completa su dataset nuovo dopo la rinomina. — Task 3.
3. Il servizio si riavvia tra «Prepara» e «Completa», o «Prepara» fallisce a metà: lo stato nel DB dice da dove ripartire; «Prepara» è ripetibile. — Task 3.
4. VM con due dischi: tutti i dischi allo stesso istante (replica spenta) prima di accendere. — Task 3 e 5.
5. L'originale accesa non risponde: spegnimento dell'originale e riaccensione della replica, con messaggio chiaro. — Task 3 e 5.

### [x] Task 1 — Fotografia della configurazione dell'originale

**File:** `backend/database.py` (modello `SyncJob`: colonne `source_config_snapshot` Text, `source_config_at` DateTime, `ritorno_stato` String(30), `ritorno_dettaglio` Text); `backend/update_db_schema.py` (quattro `_ensure_column(conn, "sync_jobs", …)`); `backend/services/sync_job_execution.py` (dove oggi legge la conf della sorgente prima di `register_vm`, righe ~250-280 e ~780); prova `backend/tests/test_ritorno_originale.py`.
**Cosa fare:** quando il job legge la configurazione della sorgente, salvarla intera in `source_config_snapshot` (sezione principale, senza le sezioni snapshot: `rimuovi_sezioni_snapshot` di `replica_identity`) con l'ora in `source_config_at`. Si salva **solo** se la sorgente non porta il segno `dapx-replica` nella description e se la corsa non è un ritorno: altrimenti una replica promossa sovrascriverebbe la fotografia buona. Per i job gemelli di un `vm_group_id` si scrive su tutti.
**Produce:** `job.source_config_snapshot: Optional[str]`.
**Verifica:** `cd backend && python -m pytest tests/test_ritorno_originale.py -q` → verde; la prova «conf con dapx-replica non sovrascrive» vista fallire prima del codice.
**Commit:** `ritorno: fotografia della configurazione dell'originale`.
**Verifica (24/11 sera):** `cd backend && .venv/bin/python -m pytest tests/test_ritorno_originale.py -q` → 15 rosse prima del codice, 15 verdi dopo (4 del task 1).

### [x] Task 2 — Logica pura

**File:** crea `backend/services/ritorno_originale.py`; prove nello stesso file di prova.
**Interfacce (funzioni pure, nessun SSH):**

```python
def nome_disco_vecchio(dataset: str, quando: datetime) -> str
# "ZFS/vm-103-disk-0" -> "ZFS/dapx-vecchio-103-disk-0-20261124-1933"

def config_originale_per_ritorno(
    snapshot_originale: Optional[str],   # job.source_config_snapshot
    config_replica: str,                 # conf viva della replica
    dischi: Dict[str, str],              # {"scsi0": "ZFS:vm-103-disk-0"} sul nodo d'origine
    quando: datetime, utente: str,
) -> Tuple[str, List[str]]               # (conf, avvisi)

def piano_ritorno(jobs: List[dict], stato_replica: str, stato_originale: str,
                  conf_originale_presente: bool) -> Dict
# {"possibile": bool, "motivo": str, "dischi": [{"job_id", "disk_name",
#   "da": dest_dataset, "a": source_dataset, "rinomina": bool}], "avvisi": [...]}
```

**Regole di `config_originale_per_ritorno`:** base = fotografia dell'originale; se manca, base = conf della replica con: suffisso del nome tolto (`dest_vm_name_suffix`), uuid e vmgenid presi da `estrai_identita_da_descrizione`, e un avviso «bridge, onboot e tag non recuperabili: controllare» (è il caso dei job nati prima di questa versione). In tutti e due i casi: righe disco riscritte da `dischi`, `unusedN` tolte, sezioni snapshot tolte, description = `Ripristinata da replica <vmid> il <data> da <utente>` senza il segno `dapx-replica`. Hardware (cores, memory, cpu, scsihw, bios, machine) preso dalla fotografia; se replica e fotografia differiscono su queste chiavi, un avviso che le elenca.
**Regole di `piano_ritorno`:** impossibile se la replica non porta il segno `dapx-replica`, se l'originale è `running`, se un job del gruppo non è syncoid; `rinomina=True` per ogni disco il cui dataset d'origine esiste.
**Verifica:** pytest → verde; viste fallire prima: bridge dell'originale rimesso (caso DTS, conf vere di 103 e 9103 copiate da `/root/dapx-bak-20261124` come dati di prova, senza segreti), nome senza suffisso, nome del disco vecchio che non combacia con `^vm-\d+-disk-\d+$`.
**Commit:** `ritorno: logica pura e prove`.
**Verifica (24/11 sera):** stesso comando, 11 prove del task 2 rosse prima e verdi dopo.

### [x] Task 3 — Passi SSH e rotte

**File:** `backend/services/ritorno_originale.py` (funzioni `async`), `backend/routers/vms.py` (tre rotte dopo `activate_dr`), prove con `ssh_service.execute` e `syncoid_service.run_sync` sostituiti da doppi.
**Rotte:**
- `GET /api/vms/node/{node_id}/vm/{vmid}/ritorno` → `piano_ritorno` più `ritorno_stato` (`nessuno` · `preparazione` · `pronto` · `scambio` · `completato` · `fallito`).
- `POST …/ritorno/prepara` body `{confirm: "RITORNA"}` → parte in sottofondo (`asyncio.create_task`), risponde subito.
- `POST …/ritorno/completa` body `{confirm: "RITORNA", attesa_avvio_s: int = 180}` → idem.

**«Prepara» (replica può restare accesa):** per ogni disco: se il dataset d'origine esiste e non è già stato messo da parte in questo ritorno, `zfs rename` verso `nome_disco_vecchio(...)` (prima: originale `stopped`, altrimenti rifiuto); poi `run_sync` con sorgente = nodo e dataset della replica, destinazione = nodo e dataset d'origine, `no_sync_snap=False`, `force_delete=False`. Alla fine `ritorno_stato="pronto"`. Ripetibile: una seconda volta fa solo l'incrementale.
**«Completa»:** richiede `pronto`. (1) `qm shutdown <replica> --timeout 300`, poi `qm status` deve dare `stopped`, altrimenti stop con errore e nessun'altra azione. (2) `run_sync` incrementale per ogni disco. (3) Copia della conf attuale dell'originale, se c'è, in `/root/dapx-bak-<AAAAMMGG>/` sul nodo; scrittura della conf da `config_originale_per_ritorno` in `/etc/pve/qemu-server/<vmid>.conf` (stesso modo di `register_vm`: heredoc, non `qm set`). (4) `qm start <vmid>`; attesa fino a `attesa_avvio_s` di `qm agent <vmid> ping` se `agent: 1`, altrimenti di `qm status` = `running` per 30 s di fila. (5a) Riuscito: replica riportata a replica (`applica_identita_replica`, `onboot 0`), job del gruppo con `is_active=True` e nodo/dataset sorgente aggiornati, `ritorno_stato="completato"`; la prossima corsa normale è incrementale perché lo snapshot dell'ultimo syncoid è comune. (5b) Fallito: `qm stop <vmid>` dell'originale, `qm start <replica>`, `ritorno_stato="fallito"` col motivo; il disco nuovo dell'originale resta dov'è.
**Verifica:** pytest → verde. Viste fallire prima: «completa» senza `pronto` rifiutata; replica non spenta → nessun `qm start` dell'originale tra i comandi registrati dal doppio; avvio fallito → `qm start <replica>` tra i comandi; nessun comando contiene `destroy`.
**Commit:** `ritorno: prepara e completa con syncoid`.
**Verifica (24/11 sera):** `cd backend && .venv/bin/python -m pytest tests/test_ritorno_originale.py -q` → 14 prove del task 3 in errore prima del codice, 29 verdi dopo; suite intera `pytest tests -q` → 564 verdi.

### [x] Task 4 — Interfaccia

**File:** `frontend/src/services/vms.ts` (tre chiamate), `frontend/src/views/VMs.vue` (nel dettaglio VM, accanto alla scheda di «Attiva DR» / «Riallinea identità», riga ~537).
**Cosa fare:** scheda «Ritorno all'originale», visibile solo sulle repliche con DR attivo o accese. Mostra il piano (dischi, da dove a dove, cosa viene messo da parte, avvisi), lo stato, e due bottoni: «Prepara ritorno» e «Completa ritorno» (attivo solo in `pronto`), tutti e due con finestra che chiede di scrivere `RITORNA` e dice in chiaro il fermo. Stato riletto ogni 5 s mentre è `preparazione` o `scambio`. Stati distinti per forma e testo, non solo per colore (Riccardo è daltonico). Si propone a Riccardo la scheda prima di scriverla.
**Verifica:** `cd frontend && npm run lint && npm run build:check` → puliti; una schermata a 1920.
**Commit:** `ritorno: scheda nell'interfaccia`.
**Verifica (24/11 sera):** `cd frontend && npm run lint` → 0 errori (44 avvisi vecchi); `npm run build:check` → pulito. Schermata a 1920 **non fatta**: in locale non c'è una replica col DR attivo da aprire; si guarda al task 5 su Domarc.

### [x] Task 5 — Prova vera a Domarc

**Dove:** Domarc, LXC 332 su `192.168.40.4`, snapshot `pre-pxrepl-ritorno-<data>` prima di aggiornare. Una VM di test nuova, piccola (Debian, 2 dischi da 4 G, agent installato), con un job di replica verso PX-NAS. Nessuna VM vera, mai la 423.
**Sequenza:** corsa di replica → spegnere la VM di test → «Attiva DR» e accensione della replica → scrivere un file nella replica → «Prepara» → «Completa» → controllare: file presente nell'originale, nome/uuid/bridge/onboot/tag dell'originale, replica spenta con identità di replica, disco vecchio presente col nome datato, corsa successiva del job incrementale e verde. Poi il giro del guasto: conf di ritorno con un bridge inesistente → l'originale non parte → la replica deve tornare accesa da sola.
**Verifica:** esiti scritti nel Registro, con comandi e ore. Alla fine VM di test, replica e dischi vecchi tolti a mano, elencati per nome.

### [x] Task 6 — Documenti e rilascio

`docs/identita-replica.md` (sezione «Ritorno all'originale»), `CHANGELOG.md`, `CONTEXT.md`, `TASKS.md`, `docs/scheda-mappa.md`; cancello completo una volta; rilascio da `main` secondo `.claude/rules/rilascio.md` (5 versioni, `frontend/dist`, tag, `gh release create`). DTS si aggiorna solo col sì di Riccardo.

## Registro

- 24/11 sera, task 1: fotografia salvata in `_try_register_vm_after_sync` (dove il job legge la conf della sorgente), quindi solo per i job con «Registra VM». Aggiunta una guardia in `execute_sync_job_task`: con un ritorno aperto (`preparazione`, `pronto`, `scambio`, `fallito`) la corsa normale non parte, perché `zfs receive -F` riporterebbe indietro il disco della replica che sta lavorando.
- 24/11 sera, task 2: le conf di prova hanno la forma di 103 e 9103 ma sono scritte a mano dai dati di `TASKS.md` (nome, bridge `vmbr_vm`/`vmbr1`, tag), non copiate da `/root/dapx-bak-20261124`: quel percorso sta su DTS-PX-04 e DTS non si tocca. `config_originale_per_ritorno` e `piano_ritorno` hanno parametri in più rispetto al piano (`vmid_replica`, `suffisso_nome`; `replica_segnata`, `fotografia_presente`, e `source_esiste`/`vm_type` nei dict dei job): senza, le regole scritte non erano calcolabili. La nota dell'originale (righe `#` del `.conf`) resta, con la riga «Ripristinata da replica…» in testa.
- 24/11 sera, task 3. Scostamenti: (a) «Prepara» spegne i job del gruppo (`is_active=False`) e «Completa» li riaccende: dopo la preparazione origine e replica hanno uno snapshot in comune, e una corsa normale farebbe `zfs receive -F` sul disco della replica accesa. (b) Se fallisce l'ultimo syncoid o la scrittura della conf, a replica già spenta, la replica viene riaccesa (il piano lo diceva solo per l'avvio fallito); non la si riaccende se era già spenta prima, né se l'originale non risulta spenta. (c) Un «Prepara» fallito lascia lo stato `fallito` e si rilancia: i dischi già messi da parte sono scritti in `ritorno_dettaglio`, non si rinominano due volte. (d) Stato rimasto a `preparazione`/`scambio` dopo un riavvio del servizio: la rotta di stato risponde `interrotto: true` e «Prepara» si può rilanciare. (e) La prova a due dischi ha trovato un difetto: il servizio lavorava solo sui job ricevuti; ora allarga sempre a tutto il `vm_group_id`. (f) Tempo massimo di syncoid nel ritorno: 24 ore (la corsa normale ne ha una, una copia completa non ci sta).
- Non provato qui, resta al task 5: syncoid vero a ruoli invertiti (chiavi SSH dal nodo della replica al nodo d'origine), `zfs rename` su uno zvol vero, scrittura della conf in `/etc/pve`, attesa dell'agent.
- 24/11 sera, task 4: scheda proposta a Riccardo oggetto per oggetto e approvata («Sì, scrivila»). Sta nel dettaglio VM sotto «Identità replica»; si vede sulle repliche col DR attivato, accese, o con un ritorno aperto. `frontend/dist` non è nel commit: si ricostruisce al rilascio (task 6).
- **Fermo qui**: task 5 (prova vera a Domarc) e task 6 (rilascio) partono solo dopo aver detto a Riccardo cosa si fa su Domarc.
- 24/11 20:05-20:15, task 5 avviato col sì di Riccardo. Snapshot dell'LXC 332 `pre-pxrepl-ritorno-20261124` su DA-PX-04. `frontend/dist` ricostruito e pubblicato (`afda7c4`), poi `./update.sh -y` nell'LXC 332: codice a `0296e0b`, le quattro colonne aggiunte a `sync_jobs`, `/api/health` healthy (versione ancora 3.26.0: il numero cambia al task 6).
- 24/11 20:15: VM di test **9801 `dapx-test-ritorno`** su DA-PX-04 (Debian 12 genericcloud, `zfs:vm-9801-disk-0` e `zfs:vm-9801-disk-1` da 4 G, `net0` su `vmbr_int` con `link_down=1`, tag `dapx-test`, onboot 0), accesa. Senza agent: l'immagine cloud non lo porta e la VM è staccata dalla rete, quindi l'attesa usa «running per 30 s» e i dati si confrontano a blocchi (checksum dello snapshot finale sui due lati) invece che con un file scritto nell'ospite. `vmbr_int` su PX-NAS non esiste: la replica nascerà su `vmbr0`, cioè il caso DTS.
- Accesso all'app: col sì di Riccardo, script `/root/dapx-prova-api.py` nell'LXC 332 che crea al momento un gettone di 5 minuti per l'utente amministratore e chiama le API locali; il gettone non è mai scritto su disco né stampato. Le chiamate sono nell'audit a nome `admin`.
- Da togliere a fine prova: VM 9801 e i suoi due dischi su DA-PX-04; replica e `ZFS-LARGE/replica/vm-9801-disk-*` su PX-NAS; dischi `zfs/dapx-vecchio-9801-*`; il job di prova; snapshot `pre-pxrepl-ritorno-20261124` dell'LXC 332.
- 24/11 20:13-20:14, job 17 e 18 (gruppo `e5489efa`, 9801 → PX-NAS `ZFS-LARGE/replica`, VMID 29801, `dest_bridge=vmbr0`) creati da `POST /api/sync-jobs/vm-replica` e lanciati: verdi, replica 29801 registrata su `vmbr0` con uuid derivato.
- **Giro buono, 20:15-20:17**: `qm stop 9801` → «Attiva DR» sulla 29801 → `qm start 29801` → «Prepara» (56 s): `zfs/vm-9801-disk-0` e `-1` rinominati in `zfs/dapx-vecchio-9801-disk-0-20261124-1915` e `…-disk-1-20261124-1916`, copia completa, replica rimasta accesa → «Completa» con attesa 60 s (47 s in tutto, replica spenta in 5 s): 9801 `running` con `name: dapx-test-ritorno`, `bridge=vmbr_int`, `onboot: 0`, `tags: dapx-test`, uuid e vmgenid originali, nota dell'originale conservata; 29801 `stopped` con uuid derivato e segno `dapx-replica`; conf di prima in `/root/dapx-bak-20261124/9801.conf.pre-ritorno-191659`; job riaccesi. Dati: lo snapshot finale `syncoid_PX-NAS_2026-11-24:20:17:06` ha lo stesso guid sui due lati (8112491860483370093 e 4490211224906258668 per il secondo disco). Corsa normale successiva (20:18): «Sending incremental», 3,3 MB, verde.
- **Difetto trovato dal primo giro del guasto (20:19-20:21)**: il ritorno è riuscito invece di fallire, perché la fotografia era ferma alla prima corsa. Era agganciata a `_try_register_vm_after_sync`, che durante la corsa esce in silenzio per le VM già registrate. Corretto in `c847734`: `fotografa_originale` è un passo a sé dopo la corsa riuscita. Riprovato alle 20:23: fotografia aggiornata col bridge nuovo.
- **Giro del guasto, 20:24-20:25**: `net0` della 9801 su `vmbr_nonc` (inesistente), corsa, «Attiva DR», replica accesa, «Prepara», «Completa»: `qm start 9801` rifiutato («bridge 'vmbr_nonc' does not exist»), replica 29801 riaccesa da sola in 17 s dall'inizio dello scambio, stato `fallito` col motivo, job spenti. Una corsa normale lanciata apposta in quello stato: «0 dischi», nessuno snapshot nuovo sulla replica.
- **Secondo difetto, vecchio**: «Attiva DR» riscriveva la descrizione così come la stampa `qm config` (`%3A`), e `qm set` la ricodificava (`%253A`); alla seconda attivazione l'identità non si leggeva più. Corretto a parte in `fix(attiva-dr)`, con prova. La scheda del ritorno ora non dipende più dalla lettura dell'identità (`110d2e1`).
- Non provato sul vero: attesa con `qm agent ping` (VM senza agent), originale sparita dal nodo, riavvio del servizio a metà, guardia della corsa normale su un job attivo (qui i job erano spenti). Coperti solo dalle prove automatiche, tranne la guardia.
- Schermata a 1920 non fatta: Chrome si ferma sull'avviso del certificato di `https://192.168.4.199` e non lo scavalco. La prova è lasciata in piedi (29801 accesa col DR attivo, ritorno `fallito`) perché Riccardo possa aprire la scheda.
- LXC 332 a `110d2e1` (20:30), healthy.
- 24/11 sera, pulizia col sì di Riccardo («Pulisci e rilascia»). Tolti: job 17 e 18 (`DELETE /api/sync-jobs/vm-group/e5489efa`, `jobs_deleted: 2`); su PX-NAS la VM 29801 (`qm destroy --purge`) e `ZFS-LARGE/replica/vm-9801-disk-0` e `-1` coi loro snapshot; su DA-PX-04 la VM 9801 coi suoi due dischi, i sei dataset `zfs/dapx-vecchio-9801-disk-0-20261124-{1915,1920,1924}` e `zfs/dapx-vecchio-9801-disk-1-20261124-{1916,1920,1925}`, le tre copie `/root/dapx-bak-20261124/9801.conf.pre-ritorno-{191659,192058,192533}` e la cartella vuota. Verifica: `qm list` e `zfs list -t all` sui due nodi senza niente che contenga 9801.
- 24/11 sera, task 6: cancello una volta (esito nel Consuntivo), 3.27.0 rilasciata da `main`, Domarc aggiornata. **Verifica:** `gh release view v3.27.0`, `/api/health` dell'LXC 332.
- 24/11 21:59-22:00, rilascio: commit `4e12991`, tag `v3.27.0`, release https://github.com/grandir66/DA-PXREPL/releases/tag/v3.27.0 (`releases/latest` e `version.json` su `raw` dicono 3.27.0). Cancello: 567 prove backend verdi, lint 0 errori, `build:check` pulita. Domarc: snapshot dell'LXC 332 `pre-pxrepl-3270-20261124` su DA-PX-04, `./update.sh -y`, `/api/health` 3.27.0 healthy, scheduler in battito. Tolti dall'LXC 332 lo script di prova e i log, e lo snapshot `pre-pxrepl-ritorno-20261124`. Restano sull'LXC 332 quattro snapshot (`pre-pxrepl-3245`, `-3250`, `-3260`, `-3270`).
- 25/11 00:07-00:08, DTS alla 3.27.0 col sì di Riccardo: snapshot LXC 124 `pre-pxrepl-3270-20261125` su DTS-PX-04, `./update.sh -y`, `/api/health` 3.27.0 healthy, chiavi del cluster 8 righe prima e dopo.

## Consuntivo
### Fatto
I sei task. La funzione è in `backend/services/ritorno_originale.py` con tre rotte in `routers/vms.py` e la scheda in `VMs.vue`; 31 prove più una per «Attiva DR». Provata sul vero a Domarc, giro buono e giro del guasto, su una VM di test a due dischi. Rilasciata nella 3.27.0.
### Mancante
- Non provato sul vero: attesa con `qm agent ping`, originale sparita dal nodo, riavvio del servizio a metà, guardia della corsa normale su un job attivo.
- La scheda non è stata guardata resa a schermo (avviso di certificato in Chrome).
### Scostamenti dal piano
- «Prepara» spegne i job del gruppo e «Completa» li riaccende; il piano non lo diceva.
- La replica si riaccende anche se falliscono l'ultimo syncoid o la scrittura della conf, non solo l'avvio.
- La fotografia è un passo a sé dopo ogni corsa riuscita, non dentro la registrazione della VM.
- VM di test senza agent e senza rete: dati confrontati col guid dello snapshot finale, non con un file scritto nell'ospite.
- Corretto a parte un difetto vecchio di «Attiva DR» (description ricodificata).
### Consigli di sviluppo
- Un «Annulla ritorno» per uscire da `fallito`/`pronto` senza completare (oggi i job restano spenti finché non si completa).
- Togliere gli snapshot `syncoid_<nodo replica>_…` della copia inversa a ritorno confermato.
- Un elenco dei dischi `dapx-vecchio-…` con età e spazio, perché qualcuno si ricordi di toglierli.
- Provare l'attesa con l'agent su una VM che ce l'ha, alla prima occasione.
