# Design: Replica file verso QNAP QuTS hero h6.0 (WORM via snapshot)

**Data:** 2026-07-17  
**Stato:** Approvato — implementazione v1 in corso  
**Progetto:** dapx-unified  
**Destinazione obbligatoria:** QNAP con **QuTS hero h6.0.x**

---

## 1. Obiettivo

Integrare in dapx-unified un modulo di **replica file monodirezionale** da sorgenti eterogenee verso una share **staging mutabile** su QNAP QuTS hero h6.0, con **immutabilità delegata al NAS** tramite **snapshot immutabili** (protection policy h6.0).

L'utente deve poter:

1. Registrare credenziali di **sorgente** e **destinazione QNAP**
2. **Sfogliare** la struttura cartelle sorgente (albero completo, lazy-loaded)
3. Selezionare una o più cartelle da sincronizzare
4. Configurare esclusioni (snapshot di sistema, file temporanei, pattern custom)
5. Schedulare job e monitorare esecuzione/log come gli altri job dapx

---

## 2. Contesto e vincoli

### 2.1 Cosa esiste già in dapx-unified

| Componente | Riuso |
|---|---|
| `scheduler.py` + cron | Schedule job file replication |
| `JobLog` | Log esecuzioni |
| `Replication.vue` + `JobsList.vue` | Hub job unificato (nuova tab/tipo) |
| Pattern wizard multi-step (`JobModal.vue`) | Nuovo wizard dedicato |
| `ssh_service.py` | Sorgenti Linux / rsync over SSH |
| `ssh_key_service.py` | Pattern distribuzione chiavi (opzionale per Linux) |
| `host_backup.py` + `HostBackupJob` | Modello job standalone più semplice di `SyncJob` |
| `notification_service.py` | Alert su failure |

### 2.2 Cosa NON esiste (gap)

- Modelli/API per endpoint NAS o server generici
- Client Synology DSM / QNAP File Station
- Browse SMB Windows
- Servizio rsync file-level dedicato (solo ad-hoc in `migration_service.py`)
- Integrazione snapshot QNAP (API non pubblica — solo documentazione/monitoraggio)

### 2.3 Vincoli QuTS hero h6.0 (verificati su documentazione QNAP)

- **Snapshot immutabili:** protection policy *"Prohibit recycle and delete until expired"* configurabile su schedule ([What's New h6.0.x](https://docs.qnap.com/operating-system/quts-hero/6.0.x/en-us/what-s-new-in-quts-hero-385FEC8.html))
- **Retention N copie:** Smart Versioning o max snapshot count ([retention policy](https://docs.qnap.com/operating-system/quts-hero/6.0.x/en-us/configuring-a-snapshot-retention-policy-EF666EE.html))
- **Only if modified:** opzione schedule per evitare snapshot inutili
- **WORM share + HBS 3 v26:** backup verso WORM sì, sync verso WORM no — **non usare come path primario**
- **API snapshot:** non documentata pubblicamente — Fase 2 gestita su QNAP, dapx coordina timing e documenta policy attesa
- **ZFS CLI:** vietato — nessun comando zfs raw da dapx

---

## 3. Architettura

### 3.1 Modello a due fasi

```
┌─────────────────────────────────────────────────────────────────┐
│ FASE 1 — dapx-unified (sync monodirezionale, share mutabile)    │
│                                                                   │
│  Sorgente ──pull──► motore rsync ──push──► QNAP /staging/...    │
│  (Synology | QNAP | Linux | Windows)                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ FASE 2 — QuTS hero h6.0 nativo (immutabilità)                   │
│                                                                   │
│  Snapshot Schedule + protection policy immutabile + retention     │
│  (configurato su Snapshot Manager, non via API dapx)             │
└─────────────────────────────────────────────────────────────────┘
```

**Principi:**

- Fase 1: rsync mirror incrementale, `--delete` ammesso sulla staging, struttura cartelle identica alla sorgente
- Fase 2: QNAP crea snapshot COW immutabili post-sync; N versioni = retention snapshot (non run completi duplicati)
- Nessuna logica WORM custom in dapx durante il transfer

### 3.2 Tipi sorgente supportati

| Tipo | Protocollo browse | Protocollo sync | Note |
|---|---|---|---|
| `synology` | DSM File Station API | rsync module / SMB | Esclusioni preset snapshot DSM |
| `qnap` | QNAP File Station API | rsync / SMB | Esclusioni snapshot QNAP |
| `linux` | SSH (`find`/`ls` o SFTP) | rsync over SSH | Riuso `ssh_service`; chiave SSH o password |
| `windows` | SMB/CIFS (smbclient / libsmb) | rsync over SSH (OpenSSH) o SMB pull | Share UNC; esclusioni VSS/shadow copy |

La destinazione è **sempre** `qnap` (QuTS hero h6.0).

### 3.3 Motore di sync per tipo sorgente

| Sorgente | Metodo preferito | Fallback |
|---|---|---|
| Linux | `rsync -avz -e ssh` | — |
| Windows (OpenSSH) | `rsync -avz -e ssh` | SMB robocopy-style via `smbclient` + rsync locale |
| Windows (solo SMB) | Mount CIFS temporaneo + rsync locale | — |
| Synology | rsync module DSM o SMB | API download (solo file piccoli — no) |
| QNAP (sorgente) | rsync o SMB | File Station API |

**Regola:** dapx esegue rsync sul **host dapx-unified** (mount/pull sorgente → push staging QNAP). Opzione futura: relay VM Linux se banda/latenza lo richiedono.

### 3.4 Struttura destinazione

```
/staging/archivio-<job-name>/
├── documenti/              ← mirror live (struttura completa)
│   └── 2026/fattura.pdf
└── contratti/
    └── ...
```

Snapshot QNAP (invisibili nel mirror live, gestite da Snapshot Manager):

```
Share: staging/archivio-<job-name>
  snap-2026-07-15_030000  [immutable, 30gg]
  snap-2026-07-16_030000  [immutable, 30gg]
  ...
```

---

## 4. Requisiti funzionali

### 4.1 Endpoint (credenziali)

- CRUD endpoint sorgente e destinazione
- Test connessione con feedback dettagliato (auth, reachability, permessi lettura/scrittura)
- Credenziali **cifrate at rest** nel DB (nuovo helper; non plaintext)
- Destinazione QNAP: verifica OS ≥ h6.0 (best-effort via API/QTS version)

### 4.2 Browse cartelle

- Albero lazy-loaded: expand nodo → fetch figli
- Struttura **completa** navigabile per profondità arbitraria
- Multi-select cartelle (checkbox)
- Stima dimensione opzionale (async, non bloccante)
- Cartelle di sistema/snapshot: **visibili ma non selezionabili** (preset exclude)
- Browse destinazione (mirror QNAP staging) in sola lettura per verifica post-sync

### 4.3 Job di replica

- Nome, sorgente, paths[], destinazione staging path
- Direzione fissa: sorgente → QNAP
- Esclusioni: preset + pattern custom glob
- `delete_on_dest`: bool (default `true` sulla staging)
- `on_source_delete`: enum `keep` | `mark_removed` (default `keep` — WORM-safe)
- Schedule cron + notify
- Run manuale, toggle attivo/disattivo, log, progresso bytes/file (se parsabile da rsync `--info=progress2`)

### 4.4 Immutabilità (informativa)

- UI step "Protezione QNAP" con istruzioni Snapshot Manager h6.0
- Campi hint: schedule snapshot, protection policy, retention mode, max snapshot, expiration days, only-if-modified
- dapx **non** crea snapshot; verifica opzionale post-sync che esista snapshot recente (se API interna disponibile in futuro — out of scope v1)

### 4.5 Esclusioni default

**Preset `nas_snapshots`:**

```
@Snapshot
@snapshots
#snapshot
.snapshot
@eaDir
#recycle
.Trash-*
@SynologyApplicationService
@ActiveBackup
```

**Preset `system_files`:**

```
.DS_Store
Thumbs.db
desktop.ini
*.tmp
*.swp
~$*
*.lnk
System Volume Information
$RECYCLE.BIN
```

**Preset `windows_vss`:**

```
~$*
*.wbk
```

---

## 5. Modello dati

### 5.1 Tabella `file_endpoints`

Endpoint riusabile (sorgente o destinazione).

```python
class FileEndpointType(str, enum.Enum):
    SYNOLOGY = "synology"
    QNAP = "qnap"
    LINUX = "linux"
    WINDOWS = "windows"

class FileEndpointRole(str, enum.Enum):
    SOURCE = "source"
    DESTINATION = "destination"
    BOTH = "both"

class FileEndpoint(Base):
    __tablename__ = "file_endpoints"

    id: int PK
    name: str                          # es. "NAS Synology ufficio"
    endpoint_type: FileEndpointType
    role: FileEndpointRole             # source | dest | both

    host: str
    port: int                          # default per tipo (5000/5001 DSM, 8080 QNAP, 22 SSH, 445 SMB)
    protocol: str                      # api | ssh | smb | rsync

    username: str
    password_enc: str                  # cifrato
    ssh_key_path: str | null           # Linux/Windows OpenSSH
    domain: str | null                 # Windows SMB

    base_path: str | null              # prefisso opzionale (es. /volume1)
    extra_config: JSON                 # rsync module, SSL verify, ecc.

    last_test_at: datetime | null
    last_test_status: str | null
    last_test_message: str | null

    created_at, updated_at
```

### 5.2 Tabella `file_replication_jobs`

```python
class FileReplicationJob(Base):
    __tablename__ = "file_replication_jobs"

    id: int PK
    name: str
    description: str | null

    source_endpoint_id: FK → file_endpoints
    dest_endpoint_id: FK → file_endpoints     # sempre QNAP h6.0

    source_paths: JSON                        # ["/documenti", "/foto/vacanze"]
    dest_staging_path: str                    # "/staging/archivio-syno"

    sync_method: str                          # rsync_ssh | rsync_smb | rsync_module

    delete_on_dest: bool = True
    on_source_delete: str = "keep"            # keep | mark_removed

    exclude_presets: JSON                     # ["nas_snapshots", "system_files"]
    exclude_patterns: JSON                    # ["*.bak", "temp/*"]

    bandwidth_limit_kb: int | null
    extra_rsync_args: str | null

    # Hint immutabilità QNAP (informativo, non eseguito da dapx)
    immutability_strategy: str = "qnap_immutable_snapshot"
    snapshot_policy_hint: JSON
    # {
    #   "schedule": "0 3 * * *",
    #   "protection": "prohibit_recycle_and_delete_until_expired",
    #   "retention_mode": "smart_versioning" | "max_count",
    #   "max_snapshots": 10,
    #   "expiration_days": 30,
    #   "only_if_modified": true
    # }

    schedule: str | null
    schedule_config: JSON | null
    is_active: bool = True

    current_status: str | null
    last_run_at, last_run_status, last_run_duration_sec
    last_bytes_transferred: int | null
    last_files_transferred: int | null
    next_run_at: datetime | null

    notify_mode, notify_subject
    created_at, updated_at
```

### 5.3 JobLog

Estendere `job_type` esistente con valore `file_replication` (nessuna nuova tabella log).

---

## 6. Backend

### 6.1 Moduli

```
backend/
  routers/
    file_endpoints.py          # CRUD + test connessione + browse
    file_replication_jobs.py   # CRUD job + run + log + progress
  services/
    file_replication/
      __init__.py
      endpoint_crypto.py       # encrypt/decrypt password
      exclude_presets.py       # preset → rsync --exclude
      synology_client.py       # auth + list_share + list
      qnap_client.py           # auth + list + write test
      linux_browser.py         # SSH directory listing
      smb_browser.py           # Windows/SMB listing (smbprotocol o smbclient)
      file_sync_service.py     # orchestrazione rsync, progress parsing
      file_replication_execution.py
  services/file_replication_schemas.py   # Pydantic
```

Registrazione in `main.py`:

```python
from routers import file_endpoints, file_replication_jobs
app.include_router(file_endpoints.router, prefix="/api/file-endpoints", tags=["file-endpoints"])
app.include_router(file_replication_jobs.router, prefix="/api/file-replication", tags=["file-replication"])
```

Migrazione colonne in `update_db_schema.py` + `Base.metadata.create_all` per tabelle nuove.

### 6.2 API endpoints

#### File Endpoints — `/api/file-endpoints`

| Method | Path | Descrizione |
|---|---|---|
| GET | `/` | Lista endpoint |
| POST | `/` | Crea endpoint |
| GET | `/{id}` | Dettaglio (no password) |
| PUT | `/{id}` | Modifica |
| DELETE | `/{id}` | Elimina (se non usato da job) |
| POST | `/{id}/test` | Test connessione |
| GET | `/{id}/browse` | `?path=&depth=1` — lista figli |
| GET | `/{id}/browse/tree` | `?path=&max_depth=N` — prefetch limitato (opzionale) |

#### File Replication Jobs — `/api/file-replication`

| Method | Path | Descrizione |
|---|---|---|
| GET | `/` | Lista job |
| POST | `/` | Crea job |
| GET | `/{id}` | Dettaglio |
| PUT | `/{id}` | Modifica |
| DELETE | `/{id}` | Elimina |
| POST | `/{id}/run` | Esecuzione manuale |
| POST | `/{id}/toggle` | Attiva/disattiva |
| GET | `/{id}/logs` | JobLog |
| GET | `/{id}/progress` | Stato live (se running) |
| GET | `/stats/summary` | Conteggi aggregati |

Autenticazione: `@require_operator` come altri router job.

### 6.3 Client browse — interfaccia comune

```python
class BrowseEntry(TypedDict):
    name: str
    path: str
    is_dir: bool
    is_excluded: bool          # preset match
    selectable: bool
    size: int | null

class EndpointBrowser(Protocol):
    async def test_connection(self) -> TestResult: ...
    async def list_children(self, path: str) -> list[BrowseEntry]: ...
```

Implementazioni: `SynologyBrowser`, `QnapBrowser`, `LinuxSshBrowser`, `SmbBrowser`.

### 6.4 Esecuzione sync

Flusso `file_replication_execution.py`:

1. Lock job (pattern `_running_jobs` scheduler)
2. Crea `JobLog` status `running`
3. Costruisce file `--exclude-from` temporaneo da preset + custom
4. Monta/accesso sorgente secondo `sync_method`:
   - **rsync_ssh:** `rsync -avz --delete --info=progress2 -e "ssh ..." user@host:/path/ /mnt/qnap-staging/dest/`
   - **rsync_smb:** mount CIFS sorgente (o dest) + rsync locale
   - **rsync_module:** `rsync rsync://user@host/module/path/`
5. Push verso QNAP staging via rsync over SSH o SMB mount
6. Aggiorna stats, `JobLog` completed/failed, notifica se configurata
7. Cleanup mount temporanei

**Dipendenze host dapx:** `rsync`, `openssh-client`, `cifs-utils` (opzionale), `smbclient` (fallback browse Windows).

### 6.5 Scheduler

Registrare in `scheduler.py` nuovo tipo job `file_replication_{id}` con stessa logica cron di `SyncJob` / `HostBackupJob`.

---

## 7. Frontend

### 7.1 Navigazione

- Nuova voce menu: **Replica file** (o tab in `Replication.vue`: "File NAS")
- Route: `/file-replication` → `FileReplication.vue`
- Sotto-route opzionale: `/file-replication/endpoints` per gestione credenziali

### 7.2 Componenti

```
frontend/src/
  views/FileReplication.vue
  views/file-replication/FileEndpoints.vue
  components/file-replication/
    FileEndpointForm.vue       # form credenziali per tipo
    FolderBrowser.vue          # albero lazy, multi-select
    FileReplJobModal.vue       # wizard 4 step
    QnapImmutabilityHint.vue   # istruzioni snapshot h6.0
    FileReplJobsList.vue       # tabella job (o estensione JobsList)
  services/fileReplication.ts
  services/fileEndpoints.ts
```

### 7.3 Wizard creazione job (4 step)

1. **Sorgente** — selezione endpoint o creazione inline; test connessione
2. **Cartelle** — `FolderBrowser` multi-select; preview esclusioni
3. **Destinazione** — endpoint QNAP h6.0 + path staging; test scrittura
4. **Regole e schedule** — delete_on_dest, esclusioni, hint snapshot, cron, notifiche

### 7.4 Form endpoint per tipo

| Campo | Synology | QNAP | Linux | Windows |
|---|---|---|---|---|
| Host | ✓ | ✓ | ✓ | ✓ |
| Porta API/SSH/SMB | 5000/5001 | 8080 | 22 | 445 |
| Username/password | ✓ | ✓ | ✓ | ✓ |
| Chiave SSH | — | — | ✓ | opzionale |
| Dominio SMB | — | — | — | ✓ |
| Verifica SSL | ✓ | ✓ | — | — |

Coerenza grafica: riuso classi `btn`, `repl-*`, card e tab da `Replication.vue` / `JobModal.vue`.

---

## 8. Setup QNAP QuTS hero h6.0 (checklist operatore)

Da documentare in UI e in README modulo:

1. Creare share staging **thin**, compressione abilitata, **senza WORM**
2. Abilitare rsync/SSH/SMB per accesso da host dapx
3. Snapshot Manager → share staging → **Schedule snapshot**
   - Orario: **almeno 1h dopo** schedule sync dapx
   - Protection: **Prohibit recycle and delete until expired**
   - Expiration: es. 30 giorni
   - Retention: Smart Versioning o max N snapshot
   - **Only if modified:** enabled
   - **Guaranteed snapshot space:** enabled
4. (Opzionale avanzato) Seconda share WORM + job HBS staging→WORM — solo compliance file-level

---

## 9. Sicurezza

- Password endpoint cifrate con chiave derivata da secret applicativo (`DAPX_SECRET_KEY` env o file `/etc/dapx-unified/`)
- Mai loggare password o payload credenziali
- Route protette `@require_operator` / `@require_admin` per CRUD endpoint
- Test connessione con timeout breve
- Mount CIFS: opzioni `uid/gid`, `file_mode`, smontaggio garantito in `finally`
- Validazione path: no path traversal (`..`) nei path browse/sync

---

## 10. Gestione errori

| Scenario | Comportamento |
|---|---|
| Sorgente irraggiungibile | Job failed, log stderr, retry opzionale (fase 2) |
| QNAP staging piena | Job failed, alert, suggerimento espansione share |
| Auth fallita | Test connessione rosso in UI; job non partono |
| rsync exit code ≠ 0 | Job failed, log completo rsync |
| File locked su staging (future WORM errata) | Warning in log; verificare che staging non abbia WORM |
| Snapshot non creato | Fuori scope v1; documentare verifica manuale Snapshot Manager |

---

## 11. Testing

### Backend

- Unit: `exclude_presets.py` → pattern rsync corretti
- Unit: mock client Synology/QNAP browse
- Integration: job rsync Linux → QNAP staging (ambiente test)
- Test connessione con credenziali invalide

### Frontend

- Wizard validazione form per ogni tipo endpoint
- FolderBrowser expand/collapse, exclude non selezionabili

---

## 12. Fuori scope v1

- Trigger snapshot QNAP via API non documentata
- Relay VM dedicata (opzione v2)
- HBS WORM vault automatico
- Sync bidirezionale
- Dedup globale cross-job
- Agent Windows installato su ogni macchina
- Browse snapshot storiche QNAP dall'UI dapx

---

## 13. Alternative valutate

| Approccio | Motivo scarto |
|---|---|
| Run completi timestampati | Spazio disco eccessivo |
| Versioning file `.versions/` in dapx | Complessità custom, WORM fragile |
| Sync diretto su share WORM | HBS/rsync non supportano sync WORM; overwrite impossibile |
| Solo HBS Synology→QNAP | Nessun controllo exclude/browse granulare da dapx; sorgente non solo NAS |
| Immutabilità durante sync | Complica rsync; snapshot h6.0 più efficiente (COW) |

---

## 14. Piano implementazione (high level)

1. **Fase A** — DB + crypto + CRUD endpoint + test connessione
2. **Fase B** — Client browse (Synology, Linux, QNAP, Windows SMB)
3. **Fase C** — Job CRUD + `file_sync_service` rsync + scheduler + JobLog
4. **Fase D** — UI endpoint + FolderBrowser + wizard job
5. **Fase E** — Integrazione tab Replication + CHANGELOG + doc setup QNAP h6.0

---

## 15. Riferimenti

- [QuTS hero h6.0 What's New](https://docs.qnap.com/operating-system/quts-hero/6.0.x/en-us/what-s-new-in-quts-hero-385FEC8.html)
- [Snapshot retention policy h6.0](https://docs.qnap.com/operating-system/quts-hero/6.0.x/en-us/configuring-a-snapshot-retention-policy-EF666EE.html)
- [Taking a snapshot + protection policy h6.0](https://docs.qnap.com/operating-system/quts-hero/6.0.x/en-us/taking-a-snapshot-254BAE5C.html)
- [Synology File Station API Guide](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf)
- [QNAP File Station API v5](https://eu1.qnap.com/dev/QNAP_QTS_File_Station_API_v5.pdf)
- [HBS WORM destination setup](https://www.qnap.com/en-us/how-to/tutorial/article/how-to-set-up-a-worm-shared-folder-as-an-hbs-backup-destination)
