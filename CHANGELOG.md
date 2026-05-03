# Changelog

Tutte le modifiche rilevanti a questo progetto vengono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

## [Unreleased]

## [3.15.0] - 2026-05-03

### Coerenza UI

Audit dedicato + tre sprint mirati per uniformare l'interfaccia.

**Foundation aggiunta**:

- `components/ui/ActionButton.vue` — bottone azione standardizzato
  (run/pause/stop/edit/delete/view/logs/info/refresh/download/upload/
  add/copy/restore/test/lock/unlock) con toni semantici hover.
- `stores/confirm.ts` — helper `confirmDelete(name, what)` e
  `confirmDangerous(title, message, confirmText)` per dialoghi
  promise-based standardizzati.
- `style.css` — utility `.h1` / `.h2` / `.h3` per la tipografia,
  `.modal-sm` / `-md` / `-lg` / `-xl` / `-full` per le dimensioni dei
  modali (z-index 1000 unificato), classe globale `.empty-state-cell`
  rifinita.
- `.data-table thead th` ora è **sticky** di default (la tabella deve
  stare in `.table-container`, gia' presente ovunque).

**Sprint 1 — visibilità**:

- `<PageHeader>` applicato a 11 viste (Nodes, VMs, Cluster, LoadBalancer,
  Logs, Settings, HostBackup, Updates, ConfigBackup, BackupJobs,
  RecoveryJobs, MigrationJobs, SyncJobs). Ogni pagina ora ha titolo +
  sottotitolo + icona Heroicons coerente, con slot `#actions` per i
  bottoni di pagina.
- 30+ `confirm()` nativi migrati a `confirmDangerous` /
  `confirmDelete` async — nessun più popup browser, dialog stilato
  promise-based ovunque.

**Sprint 3 — token migration**:

- 19 colori bianchi hardcoded (`color: #fff`, `white`, `#FFFFFF`)
  sostituiti con `var(--color-text-primary)` / `var(--color-bg-surface)`
  in 7 file (LoadBalancer, ReplicationWizard, Nodes, BackupJobs,
  Login, ecc.) — dark theme integrity migliorata.

### Backlog dichiarato

- Migrazione completa di `padding`/`margin` px → `var(--space-*)`
  (~221 occorrenze): non chiusa, basso ROI vs rischio regressioni.
- Sostituzione completa dei badge legacy con `<StatusPill>`: classi
  `.badge-*` esistenti sono già allineate alla stessa palette di
  StatusPill — migrazione cosmetica, non funzionale.
- `<EmptyState>` component nelle tabelle al posto di
  `.empty-state-cell`: richiede wrap `v-if/v-else` attorno alla table,
  più sicuro lasciare la classe stilizzata.
- Breadcrumb su rotte annidate (`settings/*`).

## [3.14.1] - 2026-05-03

### Correzioni

- **`update.sh` Node 18 → niente piu' errore di Vite**:
  rilevamento preventivo di Node < 20.19 piu' robusto + nuovo flag
  `--upgrade-node` che installa Node 20 LTS via NodeSource. In modalita'
  interattiva chiede conferma; in modalita' non interattiva (`-y` /
  `--yes`) procede automatico. Se l'utente rifiuta, il fallback sul
  `frontend/dist` precompilato avviene in silenzio (no piu' "crypto.hash
  is not a function" nello stdout). Il log della build fallita viene
  comunque salvato in `/tmp/dapx-vite-build.log`.
- **`backend/routers/updates.py` (UI updater)**: stessa logica — su
  build fallita scrive un log compatto e ricade sul dist precompilato
  invece di mostrare lo stack trace di Vite.

## [3.14.0] - 2026-05-03

### Sicurezza

- **PBS run_backup / run_restore — input sanitization completa**
  (`backend/services/pbs_service.py`): validazione regex/whitelist su
  hostname, datastore, vmid, mode, compress, vm_type, pbs_user,
  pbs_storage_id, dest_storage, backup_id (sia formato `vm/123/<ts>`
  sia volid `<storage>:backup/...`), dest_vm_name_suffix, fingerprint.
  Chiude potenziale RCE via parametri da DB controllabili.
- **PBS pct restore per LXC** (`run_restore`): scelta corretta del
  tool in base a `vm_type` (qmrestore per qemu, pct restore per lxc).
- **Login rate-limit** (`backend/routers/auth.py`): finestra rolling
  15 min, max 10 tentativi falliti per IP, ritorno 429 con Retry-After.
  Reset al primo login andato a buon fine.
- **Logout server-side effettivo** (`get_current_user`): se l'utente
  ha fatto logout (UserSession.is_active=False) il token JWT residuo
  viene rifiutato anche se non scaduto.
- **Path traversal fix** (`routers/host_backup.py`,
  `routers/config_backup.py`): helper `_safe_join` + check realpath
  contro la directory base; rifiuta nomi contenenti `/`, `\`, `.`,
  `..` o che escono dalla directory autorizzata.
- **Visibilità BackupJob filtrata** (`routers/backup_jobs.py`):
  utenti con `allowed_nodes` ristretto vedono solo job che toccano i
  loro nodi (sorgente o PBS). 403 sull'accesso diretto a job non
  visibili.
- **vm-replica payload sanitization** (`routers/sync_jobs.py`):
  `dest_pool` / `dest_subfolder` / `dest_storage` validati con regex
  ZFS-safe; `dest_vm_name_suffix` whitelisted a 50 caratteri DNS-safe.

### Stabilità / Production-readiness

- **SQLite WAL + foreign_keys + busy_timeout**
  (`backend/database.py`): event listener `connect` che attiva
  `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`,
  `busy_timeout=30000`, `temp_store=MEMORY`. Risolve "database is
  locked" sotto contesa (scheduler + API + UI polling).
- **Schema migrations transazionali**
  (`backend/update_db_schema.py`): wrap BEGIN/COMMIT con rollback su
  errore (no schema parzialmente migrato).
- **Cleanup automatico log** (`update_db_schema.cleanup_old_logs` +
  `services/scheduler._daily_log_cleanup`): JobLog > 30gg e
  AuditLog > 90gg eliminati ogni giorno alle 03:30 UTC. Evita la
  crescita illimitata del DB.
- **Health endpoint reale** (`backend/main.py`): `/api/health` ora
  verifica DB ping e scheduler vivo; ritorna 503 se uno dei due
  fallisce. Pronto per liveness probe / monitoring esterno.
- **Exception handler env-driven**: `DAPX_ENV=development` espone il
  tipo di eccezione nel body 500; in produzione resta nascosto, lo
  stack trace va sempre nei log.
- **update.sh + UI updates.py**: rilevamento preventivo di Node <
  20.19 → skip diretto al fallback su `frontend/dist` precompilato,
  niente più output di errore Vite "crypto.hash is not a function".

### Note

- Lavori posticipati al prossimo ciclo di hardening:
  - cascade `Node → Job` da `CASCADE` a `SET NULL` (cambio schema
    invasivo, richiede pianificazione migration)
  - rollback parziale automatico della replica (cleanup snapshot/
    dataset dest se `register_vm` fallisce)
  - cifratura at-rest dei secrets in DB (Fernet con chiave da env)

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
