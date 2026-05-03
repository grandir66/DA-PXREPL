# Changelog

Tutte le modifiche rilevanti a questo progetto vengono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

## [Unreleased]

## [3.13.0] - 2026-05-03

### Sicurezza / Correttezza (audit completo)

- **Scheduler hardening** (`backend/services/scheduler.py`):
  reset all'avvio dei job rimasti in stato `running` da un crash; lock
  in-memory per chiave job (no double-fire / dataset locked); `last_run`
  settato all'avvio del run (non a fine: un crash non fa più re-fire
  immediato); wrapper `_guarded_execute` che rilascia sempre il lock.
- **`SyncJob.current_status`** aggiunto (allineato a BackupJob /
  RecoveryJob); migrazione idempotente in `update_db_schema.py`.
- **Run manuale anti double-fire** (`POST /sync-jobs/{id}/run`):
  ritorna `409 Conflict` se il job e' gia' in esecuzione.
- **PBS TLS pinning** (`services/pbs_service.py`): `_get_ticket()` e
  `list_backups_api()` accettano `pbs_fingerprint` e verificano lo
  SHA-256 del cert peer prima di trasmettere le credenziali. Se il
  fingerprint non corrisponde la chiamata viene abortita.
- **SSH `authorized_keys` safe-append** (`services/ssh_key_service.py`,
  `services/syncoid_service.py`): encoding base64 della pubkey lato
  remoto. Niente piu' shell-injection con apici/backtick/newline nella
  pubkey, niente piu' "salto" su pubkey con apostrofi.
- **Syncoid input sanitization** (`services/syncoid_service.py`):
  validazione regex su dataset/host/user, whitelist `compress`, regex
  `mbuffer_size`, blacklist metacaratteri shell in `extra_args`.
- **`register_vm` race fix** (`services/proxmox_service.py`):
  validazione VMID + check combinato status/conf-file (rifiuta
  sovrascrittura silenziosa), warning su storage dest mancante.

### Aggiunte

- **Endpoint live-progress** `GET /api/sync-jobs/{id}/progress?tail=200`:
  stato corrente + tail dell'ultimo log; polling-friendly (no WebSocket).
- **Componente `JobLogViewer.vue`**: visualizzatore log full-screen con
  auto-scroll, copia, status pill animata. Integrato nella `JobsList`
  come azione "…" sui job Syncoid.

### Note

- L'endpoint `/progress` per ora esiste solo per i job Syncoid; PBS
  arrivera' nella prossima minor.
- Info-leak su `JobLog` cross-nodo (utenti con `allowed_nodes`
  ristretto): non chiuso in questa release.

## [3.12.3] - 2026-04-30

### Correzioni
- **JobModal · Destinazione**: lo storage ZFS (es. `rpool`) non compariva nella destinazione di una replica. Cause: (1) `pvesm status` ritorna i pool ZFS come `zfspool` mentre il filtro frontend cercava solo `zfs`; (2) i pool ZFS raw non registrati come storage Proxmox (tipico caso di `rpool`) non venivano elencati. Ora il backend aggiunge i pool ZFS via `zpool list` come tipo `zfs`, e il frontend tratta `zfs` e `zfspool` come equivalenti (`backend/routers/nodes.py`, `frontend/src/components/jobs/StoragePicker.vue`).

## [3.12.2] - 2026-04-30

### Correzioni
- **`update.sh`**: il CDN di `raw.githubusercontent.com` ignorava `Cache-Control` e cache-buster query, restituendo per ~5 minuti dopo un push una versione obsoleta (es. `3.12.0` mentre la release era `3.12.1`). Ora lo script usa **GitHub Releases API** (`/releases/latest`) come sorgente primaria — sempre fresca — con il raw `version.json` come fallback.

## [3.12.1] - 2026-04-30

### Correzioni
- **`update.sh`**: lo script si chiudeva silenziosamente subito dopo "Versione disponibile" senza chiedere conferma e senza aggiornare. Causa: `compare_versions` ritorna 1/2 per indicare maggiore/minore e con `set -e` attivo questo abortiva lo script prima del prompt. Ora il return code viene catturato senza far scattare `set -e`.

### Aggiunte
- **`update.sh --yes` / `-y`**: modalità non interattiva per esecuzione tramite `pct exec`, cron, pipe. Lo script rileva anche automaticamente l'assenza di TTY su stdin e assume `yes`.

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
