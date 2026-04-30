# Changelog

Tutte le modifiche rilevanti a questo progetto vengono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

## [Unreleased]

## [3.12.0] - 2026-04-30

### Aggiunte
- **Sistema notifiche globale** (`stores/toast.ts` + `components/ui/ToastContainer.vue`):
  toast non bloccanti per success/error/warning/info, sostituiscono i
  blocking `alert()` nativi. Override globale di `window.alert` in
  `main.ts` instrada automaticamente i `alert()` legacy verso i toast
  senza modificare le viste esistenti.
- **Dialog di conferma promise-based** (`stores/confirm.ts` +
  `components/ui/ConfirmDialog.vue`): per nuove viste, `confirm()`
  asincrono con titolo/messaggio/danger; quello nativo resta come
  fallback dove ancora usato.
- **Libreria UI condivisa** in `components/ui/`:
  - `Icon.vue` — set Heroicons inline (50+ icone), wrapper unico per
    sostituire gli SVG ad-hoc sparsi nelle viste.
  - `PageHeader.vue` — header coerente (titolo, sottotitolo, icona,
    slot azioni).
  - `StatusPill.vue` — pill di stato unificata
    (success/danger/warning/info/zfs/pbs/neutral) con dot/icon/pulse.
  - `EmptyState.vue`, `LoadingState.vue`, `ErrorState.vue` —
    placeholder coerenti per le tabelle e le sezioni dati.
  - `DataTable.vue` — tabella enterprise riusabile: sticky header,
    sortable per colonna, filtro di testo, paginazione, colonne
    `numeric/mono`, slot `cell-<key>` e `actions`.

### Modifiche
- **`MainLayout.vue` ridisegnato**: sidebar 240px piu' densa, navigazione
  raggruppata (Operativo / Cluster / Repliche & Backup / Sistema),
  icone via componente `Icon`, footer utente con chip + logout. I
  componenti globali `ToastContainer` e `ConfirmDialog` sono montati
  qui per essere disponibili in tutte le viste.
- **`Dashboard.vue` riscritta**: header standardizzato, KPI grid con
  icona tonale (zfs/pbs/info/neutral), tabella metriche con barre di
  progresso ed empty/loading state coerenti.
- **Pulizia emoji nei titoli** delle pagine principali (Nodi, VM, Logs,
  Cluster, Load Balancer, Host Backup, Updates, Config Backup,
  Settings, BackupJobs/RecoveryJobs/MigrationJobs/SyncJobs).
- **`main.ts`**: monta Pinia, intercetta `window.alert` e lo instrada
  al toast store (con fallback nativo se l'override fallisce).

### Note
- Le viste pesanti (LoadBalancer ~3.3k LOC, Cluster ~1.7k, Nodes ~1.1k)
  beneficiano automaticamente del nuovo `alert→toast` ma non sono state
  riscritte: il refactor incrementale puo' procedere usando i componenti
  in `components/ui/` (DataTable, PageHeader, StatusPill).

## [3.11.4] - 2026-04-30

### Correzioni
- **JobModal**: dopo aver scelto l'host sorgente, le VM ora compaiono
  correttamente. L'endpoint `/nodes/{id}/vms` non includeva `node_id` nel
  payload e il getter `vmsByNode()` dello store le filtrava tutte fuori
  (`frontend/src/components/jobs/JobModal.vue`).
- **VMs view**: il pulsante "Configura Replica" sulla riga della VM ora
  apre il nuovo `JobModal` unificato (con preset della VM) invece del
  vecchio `ReplicationWizard` (`frontend/src/views/VMs.vue`).

### Modifiche
- Aggiunta prop `presetVm` a `JobModal` per pre-compilare lo step
  "Origine" quando il modale viene aperto da una vista VM-centrica.

## [3.11.3] - 2026-04-30

### Correzioni
- Allineato `version.json` di root (rimasto a `3.10.17`) alla versione effettiva
  del backend/frontend: ora `update.sh` rileva correttamente le nuove release.
- Sincronizzato l'endpoint `/api/health` (`backend/main.py`) che restituiva una
  versione hardcoded obsoleta (`3.10.12`).


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
