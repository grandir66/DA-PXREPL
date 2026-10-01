# CLAUDE.md — DA-PXREPL (dapx-unified)

> Regole vincolanti, **sempre caricate**: restano qui solo quelle che valgono
> ovunque nel repo. Il resto sta in `.claude/rules/` e **si carica da solo**
> quando tocchi quell'area: `backend.md` (moduli, database, auth, config,
> logging, nuovi moduli; `backend/**`, `scripts/**`), `interfaccia.md` (UI,
> frontend; `frontend/src/**`), `documentazione.md` (CHANGELOG e docs;
> `CHANGELOG.md`, `README.md`, `docs/**`), `rilascio.md` (le 5 versioni, tag,
> GitHub Release; file di versione, `frontend/dist/**`, `update.sh`,
> `backend/routers/updates.py`), `layout-install.md` (layout `/opt/dapx-unified`,
> systemd, SQLite, migrazioni schema, trappola legacy; `install.sh`, `update.sh`,
> `Dockerfile`, `backend/database.py`, `backend/update_db_schema.py`).
> Sfoltito il 2026-10-01 da ~29,7k caratteri: la versione intera è in git fino
> a `5653138`.

## Cos'è e dove gira

Backend FastAPI (`backend/`, entry `backend/main.py`, router in
`backend/routers/`, servizi in `backend/services/`) + frontend Vue/Vite
(`frontend/`, `frontend/dist/` è tracciato in git). Sull'appliance vive in
`/opt/dapx-unified/backend/`, servizio systemd `dapx-unified` (porta 8420),
DB SQLite in `/var/lib/dapx-unified/dapx.db` (fuori dall'albero di codice).
Il repo ha tre worktree (`dapx-unified-wt-*`): un solo repo/ramo per commit.
Non assumere host, ambienti o credenziali: verificarli in `backend/config.env.example`,
nei file di configurazione e nel codice; segreti mai in git.

## Regole critiche (valgono ovunque)

- **Il codice esistente funziona**: verifica che il problema esista davvero prima
  di toccarlo; modifiche minimali; rollback immediato se qualcosa peggiora.
- **Se il codice nuovo rompe qualcosa, si aggiusta il NUOVO**, non l'esistente:
  wrapper, extension, feature flag, file separato, decorator/middleware. Un bug
  vero nel codice esistente si documenta e si risolve a parte, con commit dedicato.
- **Zona rossa** (confronto esplicito prima di toccare): singleton/factory,
  middleware e router di autenticazione, router di database e gestione segreti,
  configurazione globale. **Gialla** (cautela, capire le invarianti): entry point
  `backend/main.py`, layer dati comune (`backend/database.py`), sessione/token.
  **Verde**: nuovi moduli, viste, script, documentazione.
- **MAI scrivere su produzione dall'ambiente di sviluppo**; verificare il
  permesso di scrittura dell'ambiente prima di scrivere; backup prima di
  modifiche strutturali; testare in locale e su sviluppo prima del live.
- Query sempre parametriche; connessioni sempre chiuse; permessi verificati
  anche nel backend, mai solo nascosti nell'UI; mai token/credenziali/PII in
  log, errori o messaggi; mai `print()`/`console.log`/`breakpoint()` in produzione.
- Verificare quale database/sorgente usa un modulo prima di cambiare una query
  (stesso nome di tabella, struttura diversa).
- Niente dipendenze circolari, niente duplicazione di codice tra moduli, niente
  hardcode di valori configurabili, niente stili ad-hoc fuori dal sistema condiviso.
- **Deploy**: prima sviluppo, poi produzione; backup di DB/config/volumi prima
  dei deploy critici; controllare i log subito dopo; rollback sempre disponibile;
  upgrade distinto da fresh install; non copiare in modo distruttivo se path
  sorgente e di installazione coincidono; preservare DB SQLite, config utente e
  chiavi SSH del servizio.
- **Rilascio**: si fa **solo da `main`** (`git branch --show-current`), con tutti
  e 5 i file di versione allineati, `frontend/dist/` ricostruito, CHANGELOG,
  tag **e `gh release create`**: il rilascio finisce alla release, non al
  commit. Procedura intera in `.claude/rules/rilascio.md`.
- **CHANGELOG.md** aggiornato nello stesso commit per ogni modifica rilevante
  (formato e regole in `.claude/rules/documentazione.md`).

## Prima del commit

Codice testato in locale (`backend/tests`; frontend `npm run lint` e
`npm run build:check` in `frontend/`), nessun errore di sintassi/lint, nessuna
credenziale, route protette, grafica coerente, log puliti, `CHANGELOG.md`
aggiornato. Principi di fondo: modularità, sicurezza, coerenza, backup prima di
modifiche importanti, performance (query ottimizzate, niente N+1),
reversibilità. La memoria persistente dell'agente serve per preferenze e stato
delle iniziative, mai per ciò che si ricava da codice o git.

## Dove vive cosa

| Cosa | Dove |
| --- | --- |
| Regole per area | `.claude/rules/*.md` (si caricano coi `paths:`) |
| Versione (5 punti) | `version.json`, `backend/version.json`, `backend/main.py` (2), `frontend/package.json` |
| Cosa è cambiato e perché | `CHANGELOG.md` |
| Cosa è il progetto | `README.md`; script di servizio in `scripts/` (`scripts/README.md`) |
| Installazione/aggiornamento appliance | `install.sh`, `update.sh`, `deploy_lxc.sh`, `Dockerfile`, `docker-compose.yml` |
| Schede e piani | `docs/` (`docs/scheda-mappa.md` = scheda del censimento) |
