# Changelog

Tutte le modifiche rilevanti a questo progetto vengono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

## [Unreleased]

## [3.17.8] - 2026-07-17

### Correzioni
- QNAP File Station: supporto HTTPS (porta 443 / stunnel), `verify_ssl=false` di default, fallback automatico HTTP:8080 → HTTPS:443, messaggi errore chiari (`qnap_client.py`, `FileEndpointForm.vue`).

## [3.17.7] - 2026-07-17

### Correzioni
- Synology File Station: default `verify_ssl=false` per certificati auto-firmati; HTTPS su porta 5001 indipendente dalla verifica SSL; messaggio errore esplicito su certificato (`synology_client.py`, `browser_factory.py`).

## [3.17.6] - 2026-07-17

### Correzioni
- Browse Synology/QNAP: messaggi errore espliciti su timeout/rete irraggiungibile e dettaglio API mostrato in UI (`connection_errors.py`, `FolderBrowser.vue`).
- Certificato SSL auto-firmato: accetta body JSON dalla UI, hostname IP spostato nei SAN, certificati in `/var/lib/dapx-unified/certs` (`settings.py`, `generate_cert.py`).

### Modifiche
- UI replica file: gestione completa endpoint (crea, modifica, elimina, test connessione) in tabella dedicata (`FileReplication.vue`, `FileEndpointForm.vue`).
- Replica syncoid: normalizzazione centralizzata pool/subfolder/storage ZFS per evitare nomi ridondanti tipo `*-replica-replica` (`zfs_naming.py`, `zfsNaming.ts`, `JobModal.vue`).
- VM replicate: tag Proxmox **REPL** creato/assegnato automaticamente su registrazione syncoid e replica pve_native (`pve_tags.py`, `proxmox_service.py`, `pve_native_replicate_service.py`).

## [3.17.5] - 2026-07-17

### Aggiunte
- Modulo **replica file monodirezionale** verso QNAP QuTS hero h6.0: endpoint Synology/QNAP/Linux/Windows, browse cartelle, job rsync schedulati, hint snapshot immutabili (`backend/routers/file_endpoints.py`, `backend/routers/file_replication_jobs.py`, `frontend/src/views/FileReplication.vue`).
- Documentazione design e setup QNAP h6.0 (`docs/superpowers/specs/2026-07-17-nas-worm-replication-design.md`, `docs/file-replication-setup-qnap-h6.md`).

### Fix
- **Wizard replica (syncoid → PX-NAS)**: caricamento nodi all'apertura modale, dropdown storage ZFS, auto-selezione `ZFS-LARGE/replica` (`JobModal.vue`, `StoragePicker.vue`).
- **Dischi ISO/CD-ROM**: esclusi dalla replica syncoid per default; checkbox disabilitati nel wizard; config VM destinazione senza ISO montate (`proxmox_service.py`, `JobModal.vue`, `sync_jobs.py`).
- **Wizard replica (pve_native)**: storage destinazione visibile nello step Destinazione; risolto blocco con "Avanti" disabilitato senza picker (`JobModal.vue`, `StoragePicker.vue`). monitor syncoid segna `failed` dopo timeout (~6h); reconcile PVE native/BTRFS; correzione automatica log con `completed_at` ma status `started`/`running` (`sync_job_execution.py`, `sync_job_reconciliation.py`, `scripts/db_maintenance.py`).
- **Schema DB**: migrazioni per `sync_jobs.force_cpu_host`, `recovery_jobs.notify_on_each_run`, `backup_jobs.notify_on_each_run` (`update_db_schema.py`).
- **ha_store**: fetch HA/nodi via `apiClient` (JWT refresh) invece di `fetch` raw (`frontend/src/stores/ha_store.ts`).
- **VM → Backup PBS**: elenco backup dalla view Virtual Machines allineato all'inventario PBS (API + pvesh); corretto bug `storage_id` nel fallback e formato timestamp per la UI.
- **Tabella VM**: rimossa colonna "Backup PBS" sempre in *Checking…* (conteggio non caricato per performance); backup accessibili dal pulsante **Backup PBS** nella riga.

### Refactor
- **Rimozione Load Balancer (ProxLB)**: funzionalità obsoleta (Proxmox integra il bilanciamento nativo). Eliminati view, API, `proxlb_lib`, modalità `DAPX_MODE=lb`; backup cluster spostato su `/api/ha/cluster/backup-config`; redirect `/load-balancer` → Cluster & HA.
- **Cluster.vue → apiClient**: nuovo `clusters.ts`, esteso `ha.ts` (monitor, topology, HA/cluster ops); rimossi `fetch`/`axios` diretti dalla view.
- **recovery_jobs split**: estratti `recovery_job_schemas.py`, `recovery_job_helpers.py`, `recovery_job_execution.py`, `recovery_pbs_inventory.py`; router ridotto (~1800 → ~1090 righe).
- **sync_jobs split**: estratti `sync_job_schemas.py`, `sync_job_execution.py`, `sync_job_reconciliation.py`; router ridotto (~2900 → ~1500 righe).

### Rimozioni (pulizia codice morto)
- **Frontend services**: rimossi metodi API mai chiamati (loadBalancer, syncJobs, backupJobs, logs, updates, pbsInventory, auth, sshKeys, vms, pveReplication).
- **Asset Vite** `frontend/src/assets/vue.svg`, script obsoleto `deploy_beta.sh`, commenti/import morti.
- **`services/__init__.py`**: eliminati re-export inutilizzati (resta solo `ssh_service`).

### Aggiunte
- **Layout repository**: `scripts/README.md`, `scripts/dev/run_dev.py`; rimossi progetti/script obsoleti annidati.
- **Stato live sync**: modulo `sync_job_live_state.py` estratto da `sync_jobs.py`.
- **Dashboard replica in corso**: elenco job `running` nel widget salute replica.
- **Test VM group + reconcile scheduler**: `test_vm_group_sync.py`, `test_job_log_lifecycle.py`.

### Rimozioni
- Documentazione obsoleta (`gemini.md`, template Vite), script debug one-off (`scripts/debug/`), componenti Vue orfani, CLI standalone ProxLB non usata, workflow agent `.agent/`.

### Correzioni
- **Scheduler reconcile**: import errato `_reconcile_pending_vm_registrations` → `reconcile_pending_vm_registrations`.
- **catchup_vm_groups.py**: import da `vm_group_sync_service` (non più da `sync_jobs`).

### Aggiunte (precedenti)
- **Alert replica in ritardo**: notifica proattiva email/Telegram/webhook quando VM/gruppi schedulati saltano slot cron (`notification_service`, `scheduler`, cooldown 6h).
- **Dashboard pianificazione**: widget salute replica con prossima run, slot saltati e tabella VM/gruppi collassabile (`Dashboard.vue`, `replication_health_service`).
- **Script cleanup produzione**: `scripts/cleanup_production_layout.sh` archivia file legacy non tracciati su CT332.
- **Test salute replica**: copertura slot cron, aggregazione gruppi VM e alert (`test_replication_health.py`).
- **CI GitHub Actions**: pytest backend + build frontend su push/PR (`/.github/workflows/ci.yml`).
- **Salute replica in dashboard**: widget job schedulati in ritardo vs ultimo slot cron (`/api/dashboard/replication-health`, `Dashboard.vue`).
- **Inventario PBS lazy-load**: API riepilogo VM + date on-demand con cache TTL 5 min (`/pbs-nodes/{id}/backups/vms`, `/backups/vms/{vmid}`).

### Correzioni
- **Datastore PBS in elenco nodi**: `GET /pbs-nodes/` popola `datastores` via SSH/API PBS (`pbs_service.list_datastore_names`).
- **Statistiche log**: `total_transferred` calcolato sommando i campi `transferred` dei job log (`size_utils`, `logs.py`).
- **Sanoid template**: `add_dataset_config` rispetta `use_template` scelto in UI VM (`sanoid_config_service`, `vms.py`).
- **Env legacy**: fallback `DAPX_CORS_ORIGINS`, `DAPX_PORT`, `SANOID_MANAGER_DB` accanto a variabili storiche.
- **Schedule editor**: chiarito UTC vs ora locale nelle prossime esecuzioni.

### Miglioramenti
- **Refresh token JWT**: rinnovo automatico su 401 con coda richieste parallele (`frontend/src/services/api.ts`).
- **ESLint + Prettier**: configurazione frontend con script `npm run lint` / `format`.
- **Refactor sync VM group**: logica catena multi-disco in `services/vm_group_sync_service.py`; schedule condiviso in `schedule_helpers.py`.
- **CI GitHub Actions**: workflow pytest + build + lint (file in `.github/workflows/ci.yml`).
- **Replica schedulata non rieseguita**: `execute_vm_group_sync_task` saltava i dischi con `last_status=success`, quindi dopo la prima run riuscita lo scheduler non lanciava più syncoid. Run schedulata/manuale ora usa `force_rerun=True` (`backend/routers/sync_jobs.py`, `backend/services/scheduler.py`).
- **Burst di job al restart di mezzanotte**: logrotate faceva `systemctl reload` (restart del servizio); init cron usava `last_run` vecchio e sparava tutti i gruppi arretrati. Nuovo `compute_initial_next_run()` + logrotate con `copytruncate` senza reload (`install.sh`, `backend/services/scheduler.py`).
- **Scheduler in-memory con chiavi errate**: `update_job_schedule`/`remove_job` usavano `job_id` intero invece di `sync_{id}` / `vmgroup_{uuid}` — modifiche schedule da UI non applicate fino al restart (`backend/services/scheduler.py`, `backend/routers/sync_jobs.py`).
- **`update.sh` ignorava commit nuovi a parità di version.json**: ora rileva `HEAD` ≠ `origin/main` e procede con l'aggiornamento codice (`update.sh`).
- **Doppia replica con `force_rerun`**: run schedulata non attendeva dischi già `running`/`started` — rischio syncoid duplicato (`backend/routers/sync_jobs.py`).
- **Slot cron persi se job lungo**: lo scheduler avanzava `next_run` anche quando il fire veniva saltato (lock o disco busy) (`backend/services/scheduler.py`).
- **SyncJob standalone legacy**: `_execute_job` non gestiva `still_running` da syncoid — job marcati failed con replica ancora attiva; ora usa `execute_sync_job_task` (`backend/services/scheduler.py`).
- **Registrazione VM bloccata da dischi disattivati**: `_vm_group_sync_complete` contava sibling `is_active=false` (`backend/routers/sync_jobs.py`).
- **`db_maintenance.py` durante catch-up**: reset cieco di job `running` — ora richiede `--force` se ci sono job attivi (`scripts/db_maintenance.py`).
- **Inventario PBS**: nuova pagina per esplorare backup esistenti su PBS e avviare restore diretto (`frontend/src/views/PBSInventory.vue`, API `/recovery-jobs/pbs-nodes/{id}/backups`).
- **Inventario PBS — tutte le versioni**: listing via API PBS con path restore univoco per ogni snapshot (`vm/100/2024-…`); UI con toggle opzionale “solo ultima versione” (`backend/services/pbs_service.py`).

- Audit massivo bug UI/API: auth su cluster e SSH keys; fix pulizia log (`DELETE /logs/cleanup`); fix delete host backup; route logs riordinate; log di sistema allineati a `dapx-unified` (`backend/routers/clusters.py`, `ssh_keys.py`, `logs.py`, `nodes.py`, `settings.py`, `frontend/src/services/logs.ts`, `HostBackupView.vue`, `Logs.vue`, `MainLayout.vue`).
- Rimozione viste legacy duplicate: redirect `/sync-jobs`, `/backup-jobs`, `/recovery-jobs` → `/replication`; eliminati componenti orfani (`frontend/src/router/index.ts`, viste `jobs/*` e `replication/*` obsolete).
- Script debug spostati in `scripts/debug/` (fuori dal path backend produzione).
- Endpoint `POST /nodes/{id}/update-sanoid`; fix `toggleJob` sync; toast al posto di alert su Logs/Nodes/Replication (`backend/routers/nodes.py`, `frontend/src/services/syncJobs.ts`, viste correlate).

### Correzioni (fase 3 — audit profondo)
- Rimosso endpoint duplicato e rotto `POST /api/nodes/{id}/diagnostic` da `host_info.py` (shadowing di `nodes.py`).
- Fix parsing storage in restore VM (`VMs.vue`: `res.data.storages`, campi `storage`/`avail`).
- Route statiche `recovery_jobs` (`/pbs-nodes/`, `/restore`, `/node/...`) spostate prima di `/{job_id}`.
- Path frontend produzione `/opt/dapx-unified/frontend/dist` in `main.py`; host backup create richiede `require_operator`.
- Rimossi relitti `HelloWorld.vue`, `views/components/JobLogViewer.vue` duplicato; `print()` startup in `database.py` → logger.
- Migrazione completa `alert()` → toast in tutte le viste (`scripts/migrate_alerts_to_toast.py`, 12 file Vue).
- Guard admin: componente `AdminGate`, meta router `requiresAdmin`, voci menu Updates/Load Balancer visibili solo ad admin (`frontend/src/components/ui/AdminGate.vue`, `router/index.ts`, `MainLayout.vue`, `Updates.vue`, `LoadBalancer.vue`).
- Auth store: getter `isAdmin` / `isOperator`; route `/sync-jobs/stats/summary` spostata prima di `/{job_id}` (`backend/routers/sync_jobs.py`, `frontend/src/stores/auth.ts`).

### Ottimizzazioni (fase 4)
- Gate modalità `DAPX_MODE`: route full-only (`vms`, `replication`, `host-backup`, `migration-jobs`) bloccate in modalità LB; nav Cluster visibile anche in LB; sync mode da `/api/health` (`frontend/src/utils/appMode.ts`, `router/index.ts`, `MainLayout.vue`).
- Interfacce TypeScript allineate ai modelli backend per sync/backup/recovery jobs; pulizia metodi morti in `nodes.ts` e `dashboard.ts`.
- Hardening API updates: `/updates/version` espone solo `{version}`; `/updates/changelog` richiede admin (`backend/routers/updates.py`).
- Rimosso `getDownloadUrl()` con token in query string; relitti import duplicati in `config_backup.py`.
- UI Chiavi SSH in Impostazioni (admin): genera, distribuisci, test connessioni (`frontend/src/views/settings/SSHKeys.vue`, `services/sshKeys.ts`).
- Branding docstring `DAPX-Unified` in `main.py`, `database.py`, `updates.py`; config-backup e menu visibili solo ad admin.

### Correzioni (fase 5 — sicurezza + UI)
- Host backup: mutazioni con `require_operator` + `check_node_access` su job e nodi (`backend/routers/host_backup.py`, `routers/deps.py`).
- HA e recovery: scoping nodi per operatori con `allowed_nodes` su tutti gli endpoint node-scoped e job (`backend/routers/ha.py`, `recovery_jobs.py`).
- Migrazioni: modal creazione job funzionante; icona toggle corretta (`frontend/src/views/jobs/MigrationJobs.vue`).
- Repliche: pulsante attiva/disattiva job in `JobsList` (`Replication.vue`, `JobsList.vue`).

### Correzioni
- Fix aggiornamento Sanoid/Syncoid: con `force=True` bypass apt (pacchetto distro obsoleto), clone tag GitHub release e verifica post-install (`backend/services/sanoid_service.py`, `sanoid_version_service.py`, `routers/nodes.py`).
- `apt-get update` non blocca più l'installazione se un repo terze parti è rotto (es. Docker Ubuntu su nodo Debian/Proxmox).
- Fix pagina Migrazioni (e backup jobs): route lista/creazione senza trailing slash, allineate a `sync-jobs` (`backend/routers/migration_jobs.py`, `backup_jobs.py`).
- `get_current_user` accetta `sub` numerico o username (token legacy) senza HTTP 500 (`backend/routers/auth.py`).
- UI aggiornamento: feedback errori HTTP, bulk include nodi mancanti (`frontend/src/views/SanoidSyncoid.vue`).
- Fix parser `pvecm status` per formato PVE moderno (`Name:` invece di `Cluster Name:`) in `cluster_service.py`.
- Nuovo endpoint `GET /api/ha/cluster-entry` per scegliere il nodo PVE entry point del cluster (esclude standalone come PX-NAS).

### Aggiunte
- Verifica versioni Sanoid/Syncoid sui nodi PVE vs ultima release GitHub (`backend/services/sanoid_version_service.py`, `ssh_service.check_syncoid_installed`).
- API `GET /api/nodes/sanoid-syncoid/status`, `POST /api/nodes/sanoid-syncoid/update-outdated`; fix update singolo con `force=True` (`backend/routers/nodes.py`).
- Pannello Sanoid/Syncoid in pagina Nodi con confronto upstream, badge stato e aggiornamento bulk (`frontend/src/views/Nodes.vue`, `services/nodes.ts`).
- Pagina dedicata **Sanoid / Syncoid** nel menu (Repliche & Backup) con verifica automatica all'apertura (`frontend/src/views/SanoidSyncoid.vue`, `router/index.ts`, `MainLayout.vue`).
- Fix `clusters.py` test connessione: usa `cluster_service` al posto di metodo inesistente su `proxmox_service`.
- Frontend HA/Cluster usa entry point intelligente (`ha_store.ts`, `services/ha.ts`, `Cluster.vue`).

### Correzioni (replica — sessione precedente)
- Fix run manuale sync job: `BackgroundTasks` non eseguiva `execute_sync_job_task` (coroutine non awaited); il lock scheduler veniva rilasciato subito e in UI non partiva alcun log (`backend/routers/sync_jobs.py`).
- Fix stato UI job sync: `SyncJobResponse` ora espone `current_status`; lista replica e log viewer trattano `last_status=running` / log `started` come *in esecuzione* (`backend/routers/sync_jobs.py`, `frontend/src/components/jobs/JobsList.vue`, `JobLogViewer.vue`, `Replication.vue`).
- Fix falso *fallito* su sync: se syncoid/zfs receive e' ancora attivo sui nodi (timeout SSH, receive gia' in corso), lo stato resta *running* con monitor in background invece di `failed` (`backend/services/syncoid_service.py`, `backend/routers/sync_jobs.py`).
- Avanzamento replica syncoid: polling ogni 30s confronto `refer` sorgente vs `used` destinazione (ZFS), percentuale in `/progress`, log e barra nel viewer job (`backend/services/syncoid_service.py`, `backend/routers/sync_jobs.py`, `frontend/src/components/jobs/JobLogViewer.vue`).
- Fix falso *Fallito* dopo restart backend: i SyncJob non vengono più marcati `failed` allo startup se syncoid/receive e' ancora attivo sui nodi; riconciliazione async + monitor riavviato (`backend/services/scheduler.py`, `backend/routers/sync_jobs.py`).
- Fix job bloccati al 100%: `is_replication_active` non matcha più il comando diagnostico `pgrep` (falso positivo); chiusura automatica quando i processi sono terminati e reconcile periodico ogni 2 min (`backend/services/syncoid_service.py`, `backend/routers/sync_jobs.py`, `backend/services/scheduler.py`).
- Fix registrazione VM post-replica: eseguita anche al completamento via monitor; storage Proxmox derivato per sottocartella (`ZFS-LARGE/replica` → storage `ZFS-LARGE-replica`); registrazione differita fino al sync di tutti i dischi del gruppo VM (`backend/services/proxmox_service.py`, `backend/routers/sync_jobs.py`).
- Fix rilevamento storage ZFS esistente: lettura da `/etc/pve/storage.cfg` al posto di `pvesm config` (non disponibile su alcune versioni PVE); gestione errore "already defined" in creazione storage (`backend/services/proxmox_service.py`).
- Replica multi-disco: esecuzione **sequenziale automatica** di tutti i dischi del gruppo VM (run manuale, schedulato e al completamento di ogni disco); progresso **cumulativo** sulla riga VM (`backend/routers/sync_jobs.py`, `backend/services/scheduler.py`, `frontend/src/components/jobs/JobsList.vue`, `frontend/src/stores/replication.ts`, `frontend/src/views/Replication.vue`).
- Fix stato UI gruppo multi-disco: solo la riga VM e il disco attivo mostrano *In esecuzione*; dischi completati o mai avviati conservano il proprio stato (`backend/routers/sync_jobs.py`, `frontend/src/stores/replication.ts`, `frontend/src/components/jobs/JobsList.vue`).
- Fix replica iniziale su dataset placeholder vuoto: rimozione automatica del dataset dest senza snapshot (<64MB) prima di syncoid, con retry (`backend/services/syncoid_service.py`).
- Lista job replica: barra avanzamento percentuale in colonna stato quando la replica e' attiva; API `GET /sync-jobs/` espone `is_replicating` e `transfer_progress` (`backend/routers/sync_jobs.py`, `frontend/src/components/jobs/JobsList.vue`, `frontend/src/stores/replication.ts`).
## [3.17.4] - 2026-05-04

### Modifiche — Layout deterministico per install/update

Refactoring strutturale di `install.sh` e `update.sh` per eliminare alla radice
il bug di "shadowing legacy" che ha portato all'incidente del 4/5/2026 (route
nuove non visibili dopo update apparentemente riusciti, schema DB disallineato,
9 sync_jobs invisibili in UI).

- **Layout deterministico**: il backend va in `/opt/dapx-unified/backend/`,
  non più spalmato in `/opt/dapx-unified/`. `WorkingDirectory` del systemd
  unit punta a `/opt/dapx-unified/backend`.
- **install.sh**: cambia `cp -r backend/* $INSTALL_DIR/` in
  `cp -r backend/ $INSTALL_DIR/backend/`. Su upgrade da installazioni
  legacy, sposta automaticamente `main.py`/`database.py`/`update_db_schema.py`/
  `routers/`/`services/` dalla root in `_legacy_backup_TIMESTAMP/`.
- **update.sh**:
  - rileva il layout legacy **prima** del `git reset --hard` e lo sposta
    in backup (i file legacy non sono tracked dal git, quindi un reset
    non li toccherebbe);
  - se trova `WorkingDirectory=$INSTALL_DIR` nel unit, lo aggiorna a
    `WorkingDirectory=$INSTALL_DIR/backend` con `sed`;
  - esegue esplicitamente `update_db_schema.py` per allineare lo schema
    DB anche se main.py non riesce a partire (es. shadowing pre-fix).
  - pulisce `__pycache__` dopo il reset per evitare moduli stale.

### Correzioni

- **`update_db_schema.py`**: incompatibilità con SQLAlchemy 2.x.
  `engine.connect()` ora ha autobegin, `conn.begin()` esplicito causava
  `InvalidRequestError`. Sostituito con `conn.commit()`/`conn.rollback()`
  diretti sulla connection autobeginnata.

### Documentazione

- **CLAUDE.md**: nuova sezione "Layout deterministico, install.sh,
  update.sh" con regole, errori da non ripetere, checklist post-update
  deterministica e procedura di fix manuale per installazioni rotte.

## [3.17.3] - 2026-05-04

### Aggiunte

- **Storico CHANGELOG consultabile dall'UI** — la pagina
  "Aggiornamenti Sistema" ora mostra una nuova card "Storico
  Modifiche (CHANGELOG)" con bottone Mostra/Nascondi. Espandendola,
  l'app fa fetch su `GET /api/updates/changelog` e renderizza il
  contenuto raw di `CHANGELOG.md` (markdown, monospace, scroll
  fino a 600px).
  - Backend: nuovo endpoint pubblico in
    [`backend/routers/updates.py`](backend/routers/updates.py)
    che cerca `CHANGELOG.md` in più path candidati (install dir,
    layout repo, cwd) per essere robusto in dev e prod.
  - Frontend: card aggiunta in
    [`frontend/src/views/settings/Updates.vue`](frontend/src/views/settings/Updates.vue),
    metodo `getChangelog()` nel service
    [`frontend/src/services/updates.ts`](frontend/src/services/updates.ts).
    Lazy load: il fetch parte solo al primo Mostra.

### Correzioni

- **Cache browser bloccata sul vecchio `index.html`** — dopo un update
  via `update.sh` o "Aggiorna" UI, alcuni browser continuavano a
  servire la versione precedente dell'app (testi vecchi, dialog
  obsoleti come `Annulla/Annulla` corretto in v3.17.2) finché
  l'utente non faceva un hard-refresh manuale.

  Causa: il backend serviva `index.html` (e gli altri file non
  hashati del frontend) senza header `Cache-Control`, quindi il
  browser applicava la sua euristica di cache standard.

  Fix in [`backend/main.py`](backend/main.py): aggiunti header
  `Cache-Control: no-cache, no-store, must-revalidate` +
  `Pragma: no-cache` + `Expires: 0` su:
  - `GET /` (root → `index.html`)
  - `GET /{full_path:path}` (catch-all per file non `/assets/*`)

  `/assets/*` (chunk Vite con hash nel nome, immutabili) resta
  cachable a lungo come prima — quello è l'unico modo sano per
  avere update istantanei senza perdere il vantaggio della cache
  sui chunk hashati.

## [3.17.2] - 2026-05-04

### Correzioni

- **Wizard JobModal — dialog "Uscire?" con due bottoni "Annulla"**
  ambigui. Su Esc o click fuori il dialog di conferma mostrava
  `Annulla / Annulla` (entrambi con la stessa label perché avevo
  passato "Annulla" come `confirmText` mentre `cancelText` era
  "Annulla" di default). Ora il dialog ha:
  - **Continua a modificare** (cancel — torna al wizard)
  - **Esci e scarta** (confirm danger — chiude e perde le modifiche)

  Titolo cambiato in `Uscire dalla creazione?` / `Uscire dalla
  modifica?` per coerenza.

## [3.17.1] - 2026-05-04

### Correzioni — gestione log dei job di replica

Bug rilevato: durante una run lunga (vzdump 10 min, qmrestore, syncoid…)
il viewer log mostrava sempre **"Nessun log"** anche se il job stava
lavorando regolarmente. Causa: `JobLog.output` veniva scritto **solo a
fine esecuzione**, e per i job `pve_native` la `log_cb` di progresso
non veniva mai passata dal router al servizio.

Fix:

- **Header iniziale in `JobLog.output`** all'avvio di ogni run sync
  (timestamp + metodo + source/dest), così il viewer mostra subito
  qualcosa anche prima che il comando produca output.
- **Streaming via DB per `pve_native`**: il router ora costruisce un
  `log_cb` che ad ogni progress message del servizio
  (`Pre-flight…`, `vzdump in corso…`, `scp…`, `qmrestore…`,
  `Override config…`, `Replica completata in Ns`) appende una riga
  con timestamp a `JobLog.output` e committa. Il viewer (polling
  1.5s) vede l'avanzamento in tempo reale.
  - Sessione DB dedicata per il callback (no race con la transazione
    principale del task in background).
- **Append-only output finale**: il `result.output` finale del
  servizio viene ora **appeso** al log (con un separatore
  `--- output ---`) invece che sovrascriverlo, così i progress
  message scritti durante la run non vengono persi.
- `current_status='running'` viene settato esplicitamente all'avvio
  (oltre a `last_status`), mantenendo coerenza con `BackupJob` /
  `RecoveryJob`.

### Note

- Per Syncoid/BTRFS lo streaming live non è ancora attivo (i comandi
  via `ssh_service.execute` sono bloccanti, non sono streamati per
  riga). L'header iniziale però rende il viewer non più "vuoto".
  Streaming reale richiederà una variante di `ssh_service.execute`
  con callback per linea — backlog.

## [3.17.0] - 2026-05-04

### Aggiunte

- **Nuova modalità di replica VM `pve_native`** — funziona su
  **qualunque storage** (LVM-thin, qcow2-su-dir, NFS/CIFS qcow2, ZFS,
  BTRFS, RBD/Ceph) **senza richiedere ZFS, BTRFS o un PBS server**.
  Sfrutta il meccanismo Proxmox di snapshot consistente disponibile
  nelle versioni recenti.

  Pipeline orchestrata via SSH (executor = nodo source):
  1. **Pre-flight** sul source: `pveversion`, `qm/pct config`,
     `pvesm status`, spazio sufficiente in `dump_dir`.
  2. **Pre-flight** sul dest: storage attivo, VMID dest libero o
     `replace_existing` abilitato.
  3. **`vzdump --mode snapshot --compress <X> --dumpdir <DIR>
     [--bwlimit <kb>]`** sul source.
  4. **`scp`** dell'archivio al dest.
  5. (se `replace_existing`) **`qm stop` + `qm destroy --purge`** sul dest.
  6. **`qmrestore`** (o `pct restore`) **`--storage <X> --unique`** sul dest.
  7. **Override config** (nome / bridge / VLAN / CPU host / suffix) via
     `qm set` riusando le primitive del `proxmox_service` (regex-safe).
  8. **Cleanup** archivio sul dest (sempre) e sul source (se `cleanup_after`).

  ⚠️ **Non è incrementale**: ogni run trasferisce l'archivio completo.
  Per replica con incremento di banda usare `recovery_pbs` (PBS dirty
  bitmap).

- **Nuovo enum `SyncMethod.PVE_NATIVE = "pve_native"`** + 5 colonne
  nuove su `SyncJob` (con migration idempotente):
  - `dump_dir` (default runtime `/var/lib/vz/dump`)
  - `bandwidth_limit_kb` (vzdump `--bwlimit`)
  - `pve_compress` (`zstd|lzo|gzip|none`, default `zstd`)
  - `cleanup_after` (default `True`)
  - `replace_existing` (default `False`)

- **`backend/services/pve_native_replicate_service.py`** (nuovo,
  ~500 righe): orchestratore della pipeline con validazioni
  regex-safe su tutti gli input passati a SSH (no command injection),
  pre-flight robusto, cleanup parziale in caso di failure scp.

- **Frontend wizard JobModal**: nuovo `kind: 'pve_native'` accanto a
  Syncoid/Backup-PBS/Replica-PBS. Step "Avanzate" mostra blocco
  dedicato con `dump_dir`, `bandwidth_limit_kb`, `pve_compress`,
  `cleanup_after`, `replace_existing` + warning chiaro
  "replica completa ad ogni run". Tab dedicato in `Replication.vue`.

- **Endpoint `POST /api/sync-jobs/vm-replica`**: accetta
  `sync_method=pve_native` con early-return — crea **un solo `SyncJob`
  per VM** (vzdump dumpa l'intera VM in un colpo) invece di un job
  per disco come per syncoid/btrfs.

### Note di compatibilità

- I job esistenti `syncoid`/`btrfs_send`/PBS non sono toccati.
- Su nodi con backend non riavviato dopo l'update, l'opzione
  `pve_native` nel wizard è visibile ma `POST` ritornerà 422 finché
  il servizio non viene riavviato (caricamento route nuovi).

### Backlog dichiarato

- `qm remote-migrate` (PVE 8.2+) come quinta modalità: replica live
  cross-cluster con ottimizzazione disco gestita da Proxmox. Richiede
  registrazione `RemoteCluster` (API token) — fuori scope qui.
- Streaming `vzdump --stdout | ssh dest qmrestore -` (no scratch space):
  ottimizzazione opt-in futura.

## [3.16.5] - 2026-05-04

### Correzioni critiche su registrazione VM dopo replica

- **BUG GRAVE — VMID destinazione ignorato** (`services/scheduler.py`):
  `_register_vm_after_sync` chiamava `proxmox_service.register_vm` con
  `vmid=job.vm_id` (il VMID **sorgente**), ignorando completamente
  `job.dest_vm_id`. Risultato: la VM replicata veniva sempre registrata
  con il VMID del sorgente — l'utente vedeva la VM con l'ID di origine
  invece di quello scelto nel wizard, e poteva sembrare di averne due
  (una pre-esistente + una "duplicata"). Ora il scheduler usa
  `job.dest_vm_id or job.vm_id`.
- **BUG — parametri di registrazione persi**: lo stesso scheduler
  passava SOLO `hostname/vmid/vm_type/config_content` al `register_vm`,
  ignorando `dest_storage`, `vm_name_suffix`, `dest_vm_name`,
  `force_cpu_host`, `dest_node_bridges`. Tutte le scelte del wizard
  (override nome, force CPU host, mapping storage, ecc.) erano
  effettivamente no-op nelle run schedulate. Ora vengono passati tutti.

### Aggiunte (parametri rete destinazione)

- **`dest_bridge` + `dest_vlan`** sul modello `SyncJob` + migration
  idempotente. Quando impostati, il `register_vm` sostituisce le
  occorrenze di `bridge=...` (e aggiunge/sostituisce `tag=NN`) nelle
  righe `netN` del config replicato, validati con regex.
- **`dest_vm_name`** override completo del nome (precede il suffisso)
  sul modello `SyncJob`.
- **Wizard JobModal**: i campi `bridge` / `vlan` / `dest_vm_name` del
  passo "Registrazione VM" ora vengono effettivamente trasmessi al
  backend (prima erano popolati nel form ma scartati nel payload).
- **`POST /api/sync-jobs/vm-replica`**: i nuovi campi
  `dest_bridge` / `dest_vlan` / `dest_vm_name` / `force_cpu_host` sono
  validati (regex/range) e persistiti in `SyncJob`.
- **`POST /api/sync-jobs/{id}/register-vm`** (registrazione manuale):
  passa anche bridge/VLAN/nome custom al servizio.

## [3.16.4] - 2026-05-04

### Correzioni

- **JobLogViewer: fallback automatico all'endpoint legacy `/logs`** se
  `/progress` ritorna 404. Su container con backend non riavviato dopo
  l'update (o versione installata < 3.13.0), il viewer non resta più
  bloccato sul placeholder "endpoint non disponibile" — ricostruisce il
  payload combinando `GET /sync-jobs/{id}/logs?limit=1` (per output e
  ultima esecuzione) e `GET /sync-jobs/{id}` (per le metadata). Il
  polling rallenta automaticamente a 5s perché il legacy non offre
  aggiornamento live. Toast informativo "Modalità log compatibile".

## [3.16.3] - 2026-05-04

### Correzioni

- **Pulsante "Esegui" sulla riga VM ora forza la replica di tutti i
  dischi**. Su una VM con piu' dischi (piu' disk-job raggruppati per
  `vm_group_id`), il bottone ▶ era **disabilitato** sulla riga
  aggregata: cliccando non partiva nulla. Risultato: l'utente percepiva
  che "il pulsante non fa niente" e poteva eseguire solo via cron.
  - JobsList: bottone ▶ del gruppo ora attivo, con tooltip che indica
    quanti job verranno avviati.
  - Replication.vue: se il click avviene su un gruppo con piu' job
    Syncoid, chiama il nuovo endpoint dedicato che li avvia in
    parallelo.
  - Backend `POST /api/sync-jobs/vm-group/{id}/run`: forza l'esecuzione
    di TUTTI i disk-job del gruppo (anche se non schedulati), saltando
    solo i job disattivati o gia' in esecuzione (con report
    `jobs_started` / `jobs_skipped` / `skipped_reasons`). Acquisisce
    correttamente il lock `mark_running` per ciascun job per evitare
    double-fire.

## [3.16.2] - 2026-05-04

### Correzioni

- **JobLogViewer**: gestione robusta dell'errore quando l'endpoint
  `GET /api/sync-jobs/{id}/progress` ritorna 404 (es. backend non ancora
  riavviato dopo l'update, o versione installata < 3.13.0). Prima il
  componente generava un toast `"Impossibile leggere il log — API
  endpoint not found"` ad **ogni tick di polling** (1.5s) accumulando
  decine di toast a cascata; ora:
  - su 404/405 il polling si **ferma** subito
  - il toast d'errore si mostra **una sola volta**
  - nel viewer compare un placeholder informativo con la causa
    probabile e l'indicazione di riavviare il servizio
- **JobLogViewer "aggiornato Ns fa"** mostrava un valore epoch
  (~1.7 miliardi) prima della prima risposta perché `lastFetchedAt`
  partiva a `0`. Ora viene inizializzato a `Date.now()` allo start del
  polling, così il piedino mostra `0s` finché non arriva la risposta.

## [3.16.1] - 2026-05-03

### Correzioni

- **Wizard creazione job: storage destinazione non più duplicato**.
  Allo step "Destinazione" il pool ZFS (`dest_pool`) appariva, e poi
  allo step "Registrazione VM" appariva di nuovo lo "Storage destinazione
  (per i dischi)" con praticamente la stessa funzione. Ora per i job
  Syncoid il secondo selettore è nascosto e il backend usa
  automaticamente `dest_pool` come storage Proxmox di destinazione (lo
  step Registrazione VM mostra solo i campi che cambiano: VMID, nome,
  bridge/VLAN, force-cpu).
- **Errore "dataset does not exist" più parlante**.
  `syncoid_service.run_sync` ora fa un **pre-flight check**: prima di
  lanciare syncoid verifica che `source_dataset` esista realmente sul
  nodo executor. Se non esiste, l'errore restituito è
  *"Dataset sorgente 'dev/pve/vm-686-disk-0' non trovato su <host>.
  Verifica che lo storage Proxmox punti al pool ZFS corretto"*
  invece del vecchio output criptico di syncoid (che parlava di lz4 +
  ZFS resume + dataset mancante in mezzo a un blob di stderr).

## [3.16.0] - 2026-05-03

### Coerenza UI (round 2)

- **77 button con emoji** in 18 viste → `<Icon name="..." :size="14" />`
  (Heroicons inline, set unico). Coerenza visiva delle azioni
  ovunque: nelle tabelle, nei toolbar, nelle modali. Nessuna
  ridipendenza, nessun fallback unicode.
- **Modali resistenti al click accidentale**: `JobModal` (wizard
  creazione/modifica replica) e `JobLogViewer` non chiudono piu' per
  click fuori dal modale. La chiusura va fatta esplicitamente con
  "Annulla" / X / **Esc**. Su Esc/Annulla, se il form e' "sporco"
  (step > 0, VM gia' selezionata, modalita' edit) appare un dialog
  di conferma "I dati inseriti andranno persi".

### Note

- `ConfirmDialog` continua a chiudersi per click fuori — è
  intenzionale, è un dialog di sola conferma, nessun dato viene perso.

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
