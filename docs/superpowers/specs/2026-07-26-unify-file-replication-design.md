# Unificazione "Repliche file dati" — dapx-unified

> Design approvato dall'utente il 2026-07-26. Obiettivo: eliminare il doppione tra i
> due moduli di replica file presentando **un'unica voce di menu e vista "Repliche
> file dati"**. Approccio scelto: **frontend unificato, backend intatti** (Opzione B).
> Priorità: **non rompere nulla**.

## Contesto rilevato

Due moduli paralleli, entrambi replica di file/cartelle tra NAS:

| | file-replication ("Repliche") | nas-sync ("Repliche dati") |
|---|---|---|
| Scopo | Sync monodirezionale → **QNAP WORM** (immutabilità snapshot QNAP) | NAS→NAS rsync **diretto** / rclone SMB |
| Tabella job | `file_replication_jobs` | `nas_sync_jobs` |
| Endpoint | `file_endpoints` (**condivisa**) | `file_endpoints` (**condivisa**) |
| Service FE | `fileReplicationApi` | `nasSyncApi` |
| API | `/file-replication/*` | `/nas-sync/*` |

Fatti chiave: (1) l'anagrafica endpoint è **già condivisa** (stessa tabella `file_endpoints`, stesso `fileEndpointsApi`); (2) non è un doppione totale — nas-sync **non** ha l'immutabilità WORM, feature esclusiva di file-replication. Precedente in-repo: `Replication.vue` unifica già più backend (syncoid/pve/pbs) in un'unica vista a tab.

## Design (Opzione B)

**Nuovo:** `frontend/src/views/FileDataReplication.vue` — orchestratore che:
- Header "Repliche file dati" + `+ Endpoint` + `+ Nuovo job ▾` (NAS→NAS / QNAP WORM).
- Stat cards aggregate (totali/attivi/in esecuzione/falliti) sommando i due backend.
- Tab `[ Tutti | NAS→NAS | QNAP WORM ]` che filtrano un'unica tabella.
- Tabella job unificata: `nasSyncApi.list()` + `fileReplicationApi.list()` normalizzati in righe `{ type: 'nas'|'worm', id, name, source→dest, engine, schedule, last_status, is_active }`; badge di tipo; azioni (run/stop/log/edit/delete/toggle) dispatchate al servizio corretto per `type`.
- Pannello Endpoint unico (lista da `fileEndpointsApi` + test + add/edit).
- Poll 3s solo sui job in esecuzione (come le viste attuali).

**Riusati invariati:** `NasSyncJobModal`, `NasSyncLogModal`, `FileReplJobModal`, `FileReplLogModal`, `NasSyncEndpointForm` (form endpoint superset v2), `FileReplPathMapping`, `nasSyncApi`, `fileReplicationApi`, `fileEndpointsApi`.

**Menu/route:**
- `MainLayout.vue`: due voci → una "Repliche file dati".
- `router/index.ts`: nuova route `file-data-replication`; le vecchie `nas-sync`/`file-replication` diventano redirect alla nuova.

## Non rompere nulla

- Backend, tabelle, API e job esistenti **invariati**; zero migrazione dati.
- Viste vecchie `NasSync.vue`/`FileReplication.vue` restano nel repo (fuori menu) come fallback/rollback.
- Se un backend fallisce il list, la vista mostra l'altro + nota d'errore.
- `vue-tsc` a 0 + build verde prima del rilascio; deploy solo su .199 (mai .145); backup DB prima del deploy.

## Rischi

- Form endpoint: uso `NasSyncEndpointForm` (superset rsync-capabilities); verificare in impl che copra i campi usati da file-replication (stessa tabella `file_endpoints`).
- Normalizzazione righe: i due job hanno campi diversi (`dest_staging_path`+`immutability_strategy` vs `dest_base_path`+`resolved_engine`) → mappare a una riga comune per la sola visualizzazione; edit/create restano affidati ai modali nativi.
