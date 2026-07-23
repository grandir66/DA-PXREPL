# Remediation unificata dapx-unified — piano di aggiornamento

> Unione dei due audit: **handoff** (`2026-07-23-audit-remediation-handoff.md`, ID B/S/P)
> e **canvas** (`audit-completo-dapx.canvas.tsx`, ID C/S/P/Q). Deduplicato, con stato di
> verifica (23 lug 2026) e mappatura ID incrociata.
> Backup pre-remediation eseguito: CT 332 `dapx.db.backup-20260723-remediation` + env;
> rollback git `tag pre-remediation-20260723` / `v3.17.37`. CT 124 da backuppare quando
> la rete 172.16 torna raggiungibile.

## Stato di verifica

Tutti i finding critici/alti sovrapposti tra i due documenti sono stati **verificati contro il
codice reale** (io + due agent read-only). Riepilogo: nessun finding critico risultato falso;
5 ridimensionati. Note principali:

- **B5/C-06 (TOCTOU snapshot)** → ridimensionato a **cosmetico**: il doppio run è già impedito
  dal guard sincrono in testa a `execute_vm_snapshot_job` (`if job_id in _RUNNING`). Resta solo
  che il 2° chiamante riceve "ok" invece di 409.
- **B10 (Session condivisa nel gather)** → **non-bug**: le closure del `gather` non toccano la
  Session, solo attributi ORM già materializzati.
- **P1/P2/P-01 (SSH storm lista repliche)** → **parziale**: l'SSH parte solo per job in
  `running`/`failed`, non sugli idle. Priorità reale più bassa.
- **P11/P-06 (`/logs/stats` .all())** → carica finestra 7 giorni, non tutta la tabella.
- **secrets.py** → il canvas/handoff lo dà "presente in main": **falso**. Vive solo nel working
  tree non committato del branch SMTP dell'altro agente; su `main` non esiste. La remediation S4
  non può "portarlo da main" finché quel lavoro non è committato.

### Ambito d'impatto sulle installazioni in esecuzione

Le due installazioni (CT 332/124) girano via `update.sh` + systemd, **non via Docker**. Quindi
i finding Docker/Compose (**Q-07, Q-08, Q-11, Q-14**) sono reali ma **non impattano i sistemi in
esecuzione** — vanno sistemati per chi usa il container, priorità separata.

## Mappatura ID incrociata (handoff ↔ canvas)

| Tema | Handoff | Canvas | Verificato |
|---|---|---|---|
| Dual scheduler | B1 | C-01, (P-02/P-03 correlati) | ✅ |
| Injection host backup | S1 | S-01 | ✅ |
| Password PBS shell/argv | S2, S12 | S-02 | ✅ |
| Tar traversal restore | S5 | S-03 | ✅ |
| Injection description snapshot | S3 | S-04 | ✅ |
| Path traversal SPA | S11 | S-05 | ✅ |
| Segreti in chiaro DB | S4 | S-06 | ✅ |
| TLS/SSH verify off | S8/S9 | S-07 | ✅ |
| Role mapping Proxmox | S7 | S-08 | ✅ |
| JWT query/TTL/revoca | S10, S13 | S-09 | ✅ |
| SSRF webhook | S6 | S-12 | ✅ |
| TOCTOU snapshot | B5 | C-06 | ⚠️ cosmetico |
| Retention silent-fail | B4 | C-07 | ✅ |
| LXC `qm` + start_vm | B2, B3 | C-08 | ✅ |
| Dedupe notify per id | B6 | C-11 | ✅ |
| Host backup stuck running | B12 | C-10 | ✅ |
| N+1 liste | P3/P4/P5 | P-04 | ✅ |
| Daily summary pesante | — | P-05 | ✅ |
| Event loop bloccato SMTP/subprocess | P7/P8 | P-09 | ✅ (settings.py:404 è SMTP, non subprocess) |
| Pool SSH senza lock/close | B11 | P-14 | ✅ |

### Solo canvas (non nell'handoff) — verificati

- **C-02** ReferenceError `confirmDangerous` in `Nodes.vue:755` (import locale a `installSanoid`, usato da `updateSanoid`). ✅
- **C-05** no-op in `JobLogViewer.vue` (`output.value` non azzerato al cambio job). ✅ (già segnalato anche Q-02)
- **C-13** `api.ts` richieste in coda sospese 15s su refresh fallito. ✅
- **S-10** `allowed_nodes` non applicato ai target snapshot (`vm_snapshot_jobs`/`resolver`). ✅ **gap sicurezza reale**
- **S-14** log globali non filtrati per `allowed_nodes`. ✅
- **P-07** JobLog senza indici sui path caldi. ✅
- **P-10** raccolta host SSH N+1 per guest. ✅
- **P-18** processi du/SSH non terminati al timeout. ✅
- **Q-03** drift versioni: `Dockerfile APP_VERSION=3.17.4`, lockfile disallineato. ✅
- **Q-07/Q-08/Q-11** Docker/Compose non avviabili (non impatta i CT). ⚠️ da confermare in ambiente Docker
- **Q-01/Q-13** CI non esegue type-check né controlli statici backend. ✅
- **Q-09/Q-10** coverage backend 33%, zero test frontend. ✅

---

## Piano a wave (ordine di esecuzione)

Ogni wave = un rilascio `update.sh` sulle installazioni con backup DB prima. Gate: `pytest`
verde sui nuovi test + build FE + `openapi` rotte + smoke.

### Wave 0 — Critici contenuti, basso rischio breaking (ESEGUIBILE SUBITO)

Fix mirati, testabili, senza cambi di comportamento per l'utente:

1. **C-01/B1 dual scheduler** — `main.py` importa e avvia `scheduler_service` (una sola istanza).
   *Effetto reale corretto:* cron modificati non applicati fino a riavvio, update/remove sull'istanza morta. (Nessun worker Uvicorn >1: duplicherebbe di nuovo lo scheduler — vedi rischi.)
2. **S-04/S3 injection description snapshot** — `shlex.quote` sulla description + sanitizzazione `job_name` a charset sicuro in `naming.build_description`.
3. **S-01/S1 injection host backup** — password openssl via env/stdin remoto, non in shell single-quoted; validare/quotare `dest_path`.
4. **S-02+S12/S2 password PBS** — env via canale SSH o stdin; togliere `--password` da argv.
5. **S-03/S5 tar traversal** — `extractall(filter="data")` (Py3.12) o validazione membri (`..`/assoluti/symlink) prima dell'estrazione.
6. **S-05/S11 path traversal SPA** — `realpath` + `commonpath` sotto `frontend_path`, altrimenti 404.
7. **C-07/B4 retention silent-fail** — distinguere "nessuno snapshot" da "errore listing" in `get_snapshots`/`prune_vm`; su errore non potare e marcare warning.
8. **C-08/B2+B3 LXC + start_vm** — frontend passa `vm_type`; endpoint rollback dichiara/usa `start_vm`.
9. **C-11/B6 dedupe notify** — chiave `(job_type, job_id)` in `_daily_job_notifications`.
10. **C-10/B12 host backup stuck** — set `current_status="failed"` nell'except; includere `HostBackupJob` nel reconcile startup.
11. **C-02 ReferenceError Nodes.vue** — `confirmDangerous` a livello modulo (o importato in entrambe le funzioni).
12. **C-05 no-op JobLogViewer** — assegnazione `output.value = ''` al cambio job.
13. **B5/C-06** (cosmetico) — ritornare 409 se `_RUNNING` già presente, prima di `create_task`.

### Wave 1 — Sicurezza alta con decisioni/breaking

Richiedono scelte esplicite (possono rompere lab self-signed o richiedere migrazione):

- **S-06/S4 segreti in chiaro** — introdurre `services/secrets.py` (Fernet, chiave derivata da `DAPX_SECRET_KEY` con KDF+salt separato dal JWT); migrazione versionata plaintext→cipher per smtp/webhook/telegram/pbs/api/encrypt password; redaction nelle GET. ⚠️ migrazione dati.
- **S-07/S8-S9 TLS+SSH default** — `verify_ssl=True` default con opt-out esplicito; SSH `RejectPolicy`/known_hosts. ⚠️ **rompe lab self-signed** — serve UX opt-out chiara.
- **S-08/S7 role mapping** — non promuovere `Sys.Audit`→admin; risincronizzare `role`/`allowed_nodes` a ogni login.
- **S-09/S10+S13 JWT** — no token in query (o monouso short-TTL); refresh con rotazione/hash; revoca fail-closed (niente `except: pass`).
- **S-10 allowed_nodes su snapshot** — filtro autorizzativo su selector/target/job/log/progress del modulo VM snapshot.
- **S-12/S6 SSRF webhook** — solo https, blocco loopback/RFC1918/link-local/metadata dopo resolve DNS.
- **S-11 npm audit** — aggiornare axios/form-data/follow-redirects/postcss ecc.; `npm audit --omit=dev` pulito.

### Wave 2 — Prestazioni

- **P-04/P3-P5** N+1 liste (backup/recovery/host/migration/nas): preload `nodes_by_id`/subquery ultimo log.
- **P-05** daily summary: query aggregate per tipo.
- **P-09/P7-P8** SMTP e subprocess in `to_thread`/`create_subprocess_exec`.
- **P-14/B11** pool SSH: lock per chiave + `close_all()` nel lifespan shutdown.
- **P-07** indici JobLog `(job_type,job_id,started_at)`, `(started_at,status)`.
- **P-06/P11** `/logs/stats` con COUNT/GROUP BY SQL.
- **P-01/P1-P2, P-10, P-18** SSH live solo su job attivi; host N+1; kill process group du al timeout.
- **P-13/P9-P10** polling frontend: un solo controller per risorsa, stop su idle/terminale, intervalli ≥3s.

### Wave 3 — Robustezza infra + Docker + gate CI

- **C-09** errori migrazione schema fatali + versione schema.
- **C-12** `update.sh`: stage prima dello stop, trap rollback (evitare downtime).
- **C-13** `api.ts`: svuotare la coda waiter su refresh fallito.
- **Q-07/Q-08/Q-11/Q-14** Docker: `WORKDIR/PYTHONPATH /app/backend`, environment mapping YAML, binari runtime (rsync/sshpass/rclone), `.dockerignore`, digest base. *(non impatta i CT ma sblocca chi usa il container)*
- **Q-03** allineare Dockerfile/lockfile alla versione corrente.
- **Q-01/Q-13** CI: `build:check` + `lint:strict` + ruff/mypy graduale.
- **Q-09/Q-10** soglia coverage backend; Vitest minimo frontend.

### Wave 4 — Hardening/debito

S-13 (limiti upload/query), S-14 (log per allowed_nodes), S-15 (supply chain lock+pin), S-16
(setup atomico + chiavi separate), Q-04 (except generici), Q-05/Q-06 (log FE / deprecazioni),
Q-12 (env var incoerenti).

---

## Rischi breaking da gestire (decisione utente)

1. **TLS/SSH verify default → True** (S-07): rompe nodi con certificati self-signed finché non si
   fa opt-out esplicito. Da coordinare con la UI.
2. **Cifratura segreti** (S-06): richiede migrazione dati + rotazione; se sbagliata, notifiche/PBS
   smettono di funzionare.
3. **Worker Uvicorn**: NON aumentare `--workers` — duplicherebbe di nuovo lo scheduler in-process.
4. **update.sh**: già oggi fa stop→build; un errore lascia il servizio giù (C-12) — la remediation
   stessa va rilasciata con attenzione (backup DB prima di ogni wave, fatto).

## Procedura per ogni wave (vincolante)

1. Backup DB su entrambi i CT (`cp dapx.db dapx.db.backup-<wave>`).
2. Fix + test mirati nel worktree; `pytest` + build FE verdi.
3. Bump 5 versioni + CHANGELOG + rebuild dist + commit + tag + `gh release create` (flusso CLAUDE.md).
4. `update.sh --yes` su CT 332, verifica health+openapi; poi CT 124 quando raggiungibile.
5. Se un check fallisce: rollback a `git tag` precedente + ripristino `dapx.db.backup-*`.
