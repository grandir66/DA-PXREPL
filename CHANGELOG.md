# Changelog

Tutte le modifiche rilevanti a questo progetto vengono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

## [Unreleased]

### Aggiunte
- **Modulo unificato Repliche & Backup** (`frontend/src/views/Replication.vue`):
  hub VM-centrico con tab (Tutti / Repliche ZFS / Backup PBS / Replica PBS / PVE
  nativa), KPI in alto, dropdown "+ Nuovo job" che apre il modale unificato
  per Syncoid e PBS.
- **Modale unificato `JobModal`** (`frontend/src/components/jobs/JobModal.vue`):
  wizard a 5 step (Origine VM, Destinazione, Registrazione VM, Pianificazione,
  Avanzate/Notifiche) con stessa esperienza per repliche ZFS e backup/replica
  PBS; modalità edit usa lo stesso layout con campi non modificabili in
  read-only.
- **Componenti riusabili** (`frontend/src/components/jobs/`):
  - `ScheduleEditor.vue` — pianificazione "human-readable"
    (manuale / orario / ogni N ore / giornaliero / ogni N giorni / settimanale
    con giorni multipli / mensile / cron avanzato) con preview live di cron
    e prossime esecuzioni.
  - `StoragePicker.vue` — selettore storage del nodo con rescan e tipizzazione
    (zfs / pbs / any).
  - `BridgeVlanPicker.vue` — bridge dropdown con flag vlan-aware e VLAN tag,
    suggerisce le VLAN già osservate nei config VM.
  - `VMRegistrationFields.vue` — blocco riusabile per la registrazione VM su
    nodo destinazione (VMID, suffisso/nome, storage, bridge+VLAN, force-cpu,
    overwrite, start-vm); registrazione abilitata di default.
  - `JobsList.vue` — tabella enterprise con righe VM espandibili (raggruppa
    job-per-disco di una stessa VM), filtri per stato/testo, polling
    automatico ogni 10s.
- **Pinia store `replicationStore`** (`frontend/src/stores/replication.ts`):
  fonte unica di nodi, VM e job (sync + backup PBS + recovery PBS) mergati
  in un modello `UnifiedJob`.
- **Endpoint `/api/schedule/translate`** (`backend/routers/schedule.py`):
  round-trip `ScheduleConfig` ↔ cron + 5 prossime esecuzioni di anteprima.
- **Endpoint `/api/nodes/{id}/network-config`** (`backend/routers/nodes.py`):
  bridges con flag `vlan_aware` e VLAN già osservate dai config VM, usato dal
  modale di registrazione.
- **Servizio `schedule_translator`** (`backend/services/schedule_translator.py`):
  validazione, conversione e humanize della struttura `ScheduleConfig`
  (manual / hourly / every_n_hours / daily / every_n_days / weekly / monthly /
  advanced).
- **Colonna `schedule_config` JSON** su `sync_jobs`, `backup_jobs`,
  `recovery_jobs`, `host_backup_jobs` (`backend/database.py`,
  `backend/update_db_schema.py`): persistenza della struttura "human"
  accanto al cron raw, retro-compatibile.

### Modifiche
- **`backend/main.py`**: aggancia `update_db_schema()` al lifespan startup
  per applicare le ALTER TABLE idempotenti senza intervento manuale; monta
  il nuovo router `/api/schedule`.
- **Router `sync_jobs.py` / `backup_jobs.py` / `recovery_jobs.py`**:
  i Pydantic Create/Update/Response accettano e ritornano `schedule_config`;
  un helper `_resolve_schedule_pair` allinea cron e config in modo coerente
  alla create, update e bulk vm-replica.
- **`backend/services/syncoid_service.py`**: auto-recovery del lock di
  `zfs receive` orfano sulla destinazione (uccide solo i processi con
  PPID=1, abort di un eventuale resume token, retry una volta) per evitare
  errori "is already target of a zfs receive process" da job invisibili.

### Note
- I job di replica per VM con più dischi ora vengono mostrati come una
  singola riga VM espandibile (raggruppata via `vm_group_id`), mantenendo
  invariata la persistenza per-disco lato DB.
- Il cron raw è ancora editabile dalla modalità "Avanzato" del nuovo
  `ScheduleEditor` per casi non rappresentabili dai preset.
