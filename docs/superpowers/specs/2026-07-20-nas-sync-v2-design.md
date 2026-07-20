# «Repliche dati» — motore diretto rsync + fallback rclone (modulo parallelo, v2)

**Data**: 2026-07-20
**Stato**: bozza approvata a voce, in revisione utente
**Predecessore**: `2026-07-17-nas-worm-replication-design.md` (modulo attuale "Replica file → QNAP WORM")

## 1. Contesto e problema

Il modulo attuale di replica file (menù «Replica file», `/api/file-replication`) replica cartelle
da NAS sorgente verso QNAP. Per il caso principale Synology→QNAP usa **rclone SMB↔SMB in
esecuzione sul container dapx**: ogni byte transita Synology → dapx → QNAP.

Sintomi riportati dall'utente (tutti e quattro): lentezza, progress poco chiaro, job che si
bloccano/vanno rilanciati, dubbi di affidabilità. Analisi del codice: la radice comune è il
percorso dati che passa da dapx via SMB, più una serie di conseguenze (parsing regex delle stats
rclone, trucchi SMB `--modify-window`/`--size-only`, filtri `#snapshot` interpretati male da
rclone 1.60, controllo processi con pid-file e caccia agli orphan via `pgrep`).

Problemi puntuali rilevati nel modulo attuale (riferimento, non oggetto di fix qui salvo dove indicato):

- `sync_method` è un campo morto: il motore è derivato dai tipi endpoint, non dal campo.
- Percorso rsync legacy: staging `mkdtemp` nuovo a ogni run → ri-scarica tutta la sorgente.
- **Sicurezza**: `sshpass -p '<password>'` in argv, loggato con `" ".join(cmd[:8])`
  (`file_sync_service.py`, `file_replication_execution.py`). La password finisce in log e `ps`.
- Vincolo hardcoded: destinazione solo QNAP (router + UI).
- `execute_file_replication_job` ~480 righe, orchestrazione/parsing/stato mescolati.

## 2. Obiettivi

1. **Trasferimento diretto NAS→NAS**: dapx orchestratore, i dati non transitano dal container
   quando sorgente e destinazione lo permettono.
2. **Matrice di capacità** al posto dei tipi hardcoded: sorgenti Synology/QNAP/Linux/**Windows
   (SMB)**; destinazioni **QNAP e Synology** (Linux ammesso, stessa meccanica SSH/rsync).
3. `sync_method` reale: `auto | direct_rsync | rclone_smb`, con preflight che spiega la scelta.
4. Progress deterministico (rsync `--info=progress2` + `--out-format`), stop/pausa affidabili
   (PID remoto noto), resume file-level (`--partial-dir`) + checkpoint per-cartella esistente.
5. Nessuna password in argv o nei log (env `RSYNC_PASSWORD` / `sshpass -e`).

### Non-obiettivi

- Toccare o migrare il modulo esistente: **resta intatto e operativo**. I job esistenti
  continuano a girare lì. Nessuna migrazione automatica.
- Destinazione Windows (solo sorgente). Repliche bidirezionali. Multi-destinazione per job.
- Rimozione del modulo vecchio: decisione futura, fuori scope (vedi §10).

## 3. Vincolo di isolamento (richiesta esplicita utente)

Il nuovo modulo è una **verticale parallela e autonoma** («duplicare, non intaccare»):

| Cosa | Strategia |
| --- | --- |
| Router API | **Nuovo**: `/api/nas-sync` (`backend/routers/nas_sync_jobs.py`) |
| Servizi | **Nuovo package**: `backend/services/nas_sync/` |
| Tabella job | **Nuova**: `nas_sync_jobs` (nessun uso di `file_replication_jobs`) |
| Endpoint NAS | **Condivisa in lettura** la tabella `file_endpoints`; le capacità nuove vanno in chiavi **additive** di `extra_config` (JSON) che il modulo vecchio ignora |
| Codice condiviso | Solo **import read-only di funzioni pure** dal package esistente (`endpoint_crypto`, `path_utils`, `exclude_presets`, `size_utils`); nessuna modifica a quei file. Dove servono varianti → **copia-adatta** dentro `nas_sync/` |
| Stato/esecuzione | **Duplicati e riprogettati** in `nas_sync/` (contratto engine, eventi, run_state) |
| Frontend | **Nuova view** `NasSync.vue` + componenti in `frontend/src/components/nas-sync/`; nuova route `/nas-sync`; **nuova voce di menù** accanto a quella esistente |
| Scheduler | Registrazione additiva: nuovo job-type `nas_sync` in `scheduler.py` (unico touch a file esistente oltre a `main.py` per `include_router` e router frontend — pattern «registrazione accanto all'esistente» del CLAUDE.md) |
| Migrazioni DB | `update_db_schema.py`: solo `CREATE TABLE IF NOT EXISTS nas_sync_jobs` (additivo, idempotente) |

Etichetta menù (scelta utente, 2026-07-20): **«Repliche dati»** (nuova voce), lasciando
l'attuale «Replica file» invariata.

## 4. Architettura

### 4.1 Modello di capacità (`nas_sync/capabilities.py`)

Capacità per endpoint, derivate da tipo + config + esito test:

| Endpoint | rsync sorgente (SSH) | rsync destinazione (daemon) | SMB |
| --- | --- | --- | --- |
| Synology | ✅ SSH | ✅ servizio rsync DSM | ✅ |
| QNAP | ✅ SSH | ✅ «Rsync Server» QTS/QuTS | ✅ |
| Linux | ✅ SSH | ✅ (SSH o rsyncd) | opz. |
| Windows | ❌ | ❌ | ✅ |

Config aggiuntiva in `extra_config` (additiva, ignorata dal modulo vecchio):
`ssh_port` (esiste già), `rsync_module`, `rsync_user`, `rsync_password_enc` (cifrata con
`endpoint_crypto`), `rsync_port` (default 873), `capabilities_tested` (esiti per-capacità con
timestamp).

### 4.2 Selezione motore

`job.sync_method`: `auto` (default) | `direct_rsync` | `rclone_smb`.

`auto`: se sorgente ha capacità *rsync sorgente* **e** destinazione ha *rsync destinazione*
→ `direct_rsync`; altrimenti `rclone_smb`. Il motore risolto è salvato nel log di ogni run.
Forzatura manuale possibile; il preflight blocca con messaggio azionabile se i prerequisiti
mancano.

### 4.3 Contratto engine (`nas_sync/engine.py`)

Interfaccia comune con due implementazioni:

- `DirectRsyncEngine` (`nas_sync/engine_direct_rsync.py`) — nuovo.
- `RcloneSmbEngine` (`nas_sync/engine_rclone.py`) — copia-adatta dell'attuale `rclone_sync.py`,
  generalizzata (niente parsing path solo-Synology) e con output **JSON strutturato**
  (`--use-json-log --stats-log-level NOTICE`) al posto delle regex.

Entrambe emettono lo **stesso modello di eventi**:

```python
@dataclass
class SyncEvent:
    phase: str                # starting | scanning | copying | done
    last_file: str | None
    files_new: int; files_replaced: int; files_skipped: int; files_deleted: int
    bytes_done: int | None; bytes_total: int | None
    speed: str | None; eta_seconds: int | None
    raw_line: str             # per log completo
```

L'orchestratore (`nas_sync/execution.py`) è engine-agnostico: risolve il motore, consuma eventi,
aggiorna `run_state` (checkpoint per-cartella, catalogo du — logica copia-adattata da
`file_replication_state.py`/`synology_du.py`), gestisce pausa/stop/errori. Obiettivo: nessuna
funzione oltre ~120 righe.

### 4.4 Motore diretto — meccanica

dapx apre SSH sulla **sorgente** ed esegue lì:

```bash
export RSYNC_PASSWORD='<password modulo>'   # via env sul canale SSH, mai in argv
rsync -a --info=progress2 --out-format='%i %n' --partial-dir=.dapx-partial \
      [--exclude-from=-] [--bwlimit=N] [--delete-after] \
      /volume1/SHARE/path/  rsync://utente@DEST_HOST:873/MODULO/path/
```

- **Destinazione = demone rsync nativo** (DSM/QTS lo hanno di serie). Niente scambio chiavi
  SSH tra le due NAS.
- **Auth dapx→sorgente**: chiave SSH di dapx (riuso `ssh_key_service` per installarla);
  fallback password via `sshpass -e` (env `SSHPASS`). Mai credenziali in argv/log.
- **Esclusioni**: lista exclude passata via stdin (`--exclude-from=-`). A livello filesystem gli
  snapshot Synology (`@sharesnap`) e QNAP non sono visibili → sparisce l'intera classe di
  problemi `#snapshot` di rclone. Restano exclude per `@eaDir`, `#recycle`, cestini, file OS
  (riuso `exclude_presets` per le liste rsync).
- **Progress**: `--info=progress2` (stderr: byte, %, velocità, ETA affidabili) +
  `--out-format '%i %n'` (stdout: una riga per file, con itemize per distinguere
  nuovo/aggiornato/eliminato) → mappati su `SyncEvent`.
- **PID remoto**: wrapper `echo $$; exec rsync …` → prima riga = PID sulla sorgente.
  Stop = `ssh kill -TERM -- -PID` (process group remoto) + terminazione sessione SSH locale.
- **Resume**: `--partial-dir=.dapx-partial` (file-level) + checkpoint per-cartella in
  `run_state` (folder-level), stessa UX attuale Pausa/Riprendi/Da capo.
- **Exit code mappati** in italiano: 0 ok; 23/24 warning parziale («file spariti/permessi
  durante la copia») non fatale, elencati nel report; 12/30 errore rete/daemon con hint;
  255 errore SSH.

### 4.5 Preflight (`nas_sync/preflight.py` + endpoint API)

Check in sequenza, ognuno con esito + rimedio suggerito:

1. SSH sorgente raggiungibile e autenticato.
2. `rsync --version` presente sulla sorgente.
3. Porta rsyncd destinazione raggiungibile **dalla sorgente** (`nc -z`/`timeout … bash -c` via SSH).
4. Modulo rsync accessibile in scrittura (`rsync --list-only` + touch di prova opzionale).

Per motore rclone: check SMB sorgente/destinazione (riuso client esistenti via import).

## 5. Modello dati

Tabella **`nas_sync_jobs`** (nuova; campi principali — stessi concetti del modulo attuale dove
ha senso, così l'eventuale import futuro è banale):

`id, name, description, source_endpoint_id, dest_endpoint_id, source_paths(JSON),
dest_base_path, sync_method('auto'), resolved_engine, delete_on_dest(bool, default false),
exclude_presets(JSON), exclude_patterns(JSON), bandwidth_limit_kb, rclone_size_only(bool — solo
motore rclone), schedule, schedule_config(JSON), is_active, notify_mode, notify_subject,
snapshot_policy_hint(JSON — hint QNAP/Synology per dest), run_state(JSON), current_status,
last_run_at/status/duration_sec, last_bytes_transferred, last_files_transferred, next_run_at,
created_at, updated_at`

`JobLog` riusato con `job_type="nas_sync"` (tabella log già generica: nessuna modifica schema).

## 6. API (`/api/nas-sync`)

Speculari al modulo attuale (stessa UX) più le novità:

- CRUD job, `run` (con `?fresh=`), `stop`, `toggle`, `logs`, `progress`, `stats/summary`,
  `refresh-catalog` — semantica identica all'attuale.
- **`POST /jobs/{id}/preflight`** — esegue i check §4.5, ritorna lista `{check, ok, message, hint}`.
- **`GET /endpoints/{id}/capabilities`** — capacità risolte + esiti test per-capacità.
- **`POST /endpoints/{id}/test-capability`** — testa una capacità specifica (ssh | rsyncd | smb | api).

Endpoint NAS: si riusa il CRUD esistente `/api/file-endpoints` (tabella condivisa); il modulo
nuovo aggiunge solo le rotte capacità sopra, nel **proprio** router.

Autenticazione: `get_current_user` per letture, `require_operator` per scritture (pattern attuale).

## 7. Frontend

Nuova route `/nas-sync` + voce menù **«Repliche dati»**; l'attuale «Replica file» resta.

Componenti nuovi in `frontend/src/components/nas-sync/` (copia-adatta dei corrispondenti
`file-replication/` dove la struttura regge; import diretto di utility pure TS dove possibile):

- **`NasSync.vue`** (view): header generico («Replica dati NAS», sottotitolo multi-vendor),
  stat cards, tabella endpoint **con colonna Capacità** (chip `SSH ✓` `rsync ✓` `SMB ✓`
  dall'ultimo test), tabella job con **chip motore** (`rsync diretto` / `rclone SMB`) nella
  colonna Replica; badge stato e controlli Pausa/Riprendi/Da capo identici all'attuale.
- **`NasSyncEndpointForm.vue`**: come l'attuale ma con ruolo «Destinazione» generico e sezioni
  condizionali: SSH (Synology/QNAP/Linux; nota «usato per replica diretta e catalogo du») e
  Servizio rsync (solo ruolo destinazione: modulo, utente, password, porta 873). Test
  per-capacità con esito inline.
- **`NasSyncJobModal.vue`** (wizard 4 step come oggi):
  - Step 3 Destinazione: dropdown filtrato per capacità destinazione (QNAP, Synology, Linux);
    hint immutabilità QNAP solo se dest QNAP (variante snapshot btrfs se dest Synology).
  - Step 4 Regole: **pannello Motore** — scelta `auto` risolta con motivazione leggibile
    («Diretto rsync: Synology (SSH ✓) → QNAP (rsync ✓) — i dati non passano da dapx»), select
    per forzare, bottone «Verifica prerequisiti» → preflight con esiti per check. Opzioni
    condizionali al motore: checkbox rclone (`--size-only`…) solo con motore rclone; con
    diretto restano delete-on-dest, bwlimit, exclude.
- **Log/progress modal e catalogo cartelle**: copia-adatta di `FileReplLogModal.vue` /
  `FileReplFolderCatalog.vue`; consumano lo stesso modello eventi → differenze minime.

Service TS nuovo: `frontend/src/services/nasSync.ts`.

## 8. Gestione errori

- Preflight fallito → il run non parte; messaggio con rimedio (es. «Attiva Rsync Server sulla
  QNAP: Pannello di controllo → Applicazioni → Rsync Server»).
- Caduta SSH/rete a metà run → stato `paused` con checkpoint (come oggi), riprendibile.
- Exit code rsync mappati (§4.4); 23/24 → run `success` con warning elencati nel report.
- Riavvio backend con job `running` → riconciliazione a `idle`/`paused` (pattern
  `reconcile_stale_running_jobs` copiato nel nuovo modulo).
- Nessun segreto in log: comandi loggati con redaction (`rsync://utente@host` senza password;
  env mai loggati).

## 9. Testing

Unit (pattern dei test esistenti, `backend/tests/test_nas_sync_*.py`):

- builder comando rsync remoto (excludes, bwlimit, delete, partial-dir, redaction);
- parser `--info=progress2` e `--out-format` (itemize → new/replaced/deleted/skipped);
- resolver capacità + logica `auto`;
- preflight (mock SSH) con esiti/hint;
- engine rclone: parsing JSON log;
- stato: checkpoint/resume per-cartella (riadattati dai test esistenti).

Verifica manuale sul campo: job di prova Synology→QNAP in diretto su share piccola, poi share
grande; confronto durata run incrementale vs modulo attuale; test Pausa/Riprendi/Stop; test
Windows→QNAP via rclone.

## 10. Convivenza e futuro

- I due moduli convivono senza interferenze (tabelle job separate, router separati, stessa
  tabella endpoint usata in modo additivo).
- Non schedulare lo **stesso path sorgente/destinazione** su entrambi i moduli contemporaneamente
  (documentato in UI con nota nel wizard).
- Possibile fase futura (fuori scope): «Importa job dal modulo Replica file» (mapping 1:1 dei
  campi) e successivo pensionamento del modulo vecchio.

## 11. Fix di sicurezza contestuale (unica eccezione al non-toccare)

La falla password-in-argv del modulo **esistente** (`sshpass -p`, §1) resta nel codice vecchio se
non lo tocchiamo. Proposta: fix minimale e separato (commit dedicato) che passa a `sshpass -e`
e toglie il log del comando con credenziali — 2 righe, zona gialla, previa conferma utente.
Decisione rimandata alla revisione di questa spec.
