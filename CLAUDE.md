# Istruzioni per Claude Code — Linee guida universali di progetto

Documento di riferimento per **sviluppo, manutenzione e documentazione**. Contiene direttive operative trasversali da applicare in ogni progetto in cui questo file viene incluso.

---

## Contesto

Prima di operare su un progetto, Claude deve **rilevare automaticamente**:

- **Stack tecnologico**: linguaggi, framework backend (es. FastAPI, Flask, Express), framework frontend (es. Vue, React), tipo di build (Vite, webpack), gestore pacchetti.
- **Struttura del repository**: posizione di backend, frontend, scripts, eventuali directory `docs/`, `conf/`, `config/`.
- **Strumenti di deploy**: presenza di `install.sh`, `Dockerfile`, `docker-compose.yml`, script in `scripts/`, target di runtime (container, LXC, bare-metal, cloud).
- **Convenzioni esistenti**: leggere `README.md`, `CHANGELOG.md`, eventuali `.cursorrules`, e i file di configurazione principali prima di proporre modifiche.

**Non assumere** ambienti, host o credenziali: verificare sempre nei file di configurazione del progetto.

---

## Architettura e Moduli

### Principio di modularità
Ogni modulo/router/servizio deve essere **completamente separato** dagli altri:
- Riutilizzare codice utile (importare funzioni/classi, non duplicare).
- Coerenza con stile e pattern già presenti nel codice esistente.
- Nessuna dipendenza circolare tra moduli.
- Registrazione esplicita nel punto di ingresso dell'applicazione (es. `app.py`, `main.py`, `index.ts`, router root).

### Pattern modulo (adattabile)
La struttura concreta cambia con lo stack, ma il principio resta:
- **Layer dati**: file/modulo dedicato all'accesso a database o servizi esterni.
- **Layer route/API**: definizione endpoint con autenticazione/autorizzazione.
- **Layer presentazione**: template/componenti UI dedicati.
- **Configurazione**: file dedicato se il modulo ha parametri propri.

---

## Database e accesso dati

### Regole critiche
1. **MAI scrivere su produzione** dall'ambiente di sviluppo.
2. **Sempre verificare** se l'ambiente corrente consente operazioni di scrittura prima di eseguirle.
3. **Sempre** usare query parametriche (no SQL injection): `cursor.execute(query, params)`.
4. **Sempre** chiudere connessioni — preferire context manager o `try/finally`.
5. **Backup** prima di modifiche strutturali importanti.
6. **Verificare quale database/sorgente** usa il modulo prima di modificare query: lo stesso nome di tabella può esistere in database diversi con strutture differenti.
7. **Testa sempre** su locale prima di promuovere in produzione.
8. **Migrazioni**: usare lo strumento di migrazione del progetto (Alembic, Prisma, Knex, …) se presente, evitare DDL ad-hoc.

### Pattern accesso
- Centralizzare credenziali e routing in file di configurazione, mai hardcoded.
- Esporre helper/factory per ottenere connessioni con il giusto livello di permesso (read-only vs read-write).
- Distinguere chiaramente sorgenti **locali** (cache, stato applicativo) da sorgenti **remote** (gestionali, sistemi esterni).

---

## Autenticazione e Permessi

### Principi
- Ogni route/endpoint deve dichiarare esplicitamente il livello di autenticazione richiesto (decorator, middleware, guard).
- I permessi vanno verificati **anche nel backend**, non solo nascondendo elementi nel template/UI.
- Mai esporre token, chiavi API o credenziali nei log, nelle risposte di errore o nei messaggi utente.
- Le sessioni devono avere scadenza ragionevole; i token devono essere revocabili.

### Ruoli tipici (da adattare)
- **admin**: accesso completo
- **standard / operatore**: accesso operativo, no amministrazione
- **readonly**: solo visualizzazione

### Pattern protezione (esempio generico)
```python
@router.get("/risorsa")
@require_admin           # decoratore o dipendenza del framework
def handler(...):
    if not user_can_access(user, "modulo_id"):
        raise HTTPException(403)
    ...
```

---

## Configurazione

### Regole
1. **YAML/JSON/ENV preferito su valori hardcoded** — usare `config.get(key, default)` con fallback.
2. **Mai committare** credenziali, token, chiavi private in git. Usare `.env`, secret manager o file `*.local.*` ignorati da git.
3. **File di override per ambiente** (es. `*.production.yaml`) per differenziare dev/staging/prod.
4. **Validare** i valori letti da configurazione (tipo, range, presenza).
5. **Documentare** le variabili di configurazione (es. `config.env.example`, `.env.example`).

---

## Interfaccia Utente

### Coerenza grafica (OBBLIGATORIA)
Ogni progetto ha già un proprio linguaggio visivo: **studiarlo prima di disegnare nuove schermate**.

1. **Ispeziona** i template/componenti esistenti per identificare: palette colori, tipografia, spacing, componenti base (bottoni, badge, card, tabelle, form, modali, alert, tab).
2. **Riusa** classi CSS, componenti condivisi e layout esistenti — non introdurre stili ad-hoc.
3. **Per modifiche significative** all'interfaccia di un modulo: prima di scrivere codice, descrivere all'utente **oggetto per oggetto** (header, tabella, filtri, form, modali, badge…) quale componente esistente verrà usato e come, attendendo conferma.
4. **Se manca un componente**, proporre prima di aggiungerlo al sistema condiviso (design system / libreria componenti / file CSS comune), poi usarlo nel modulo.
5. **Tabelle dati con molte righe**: header sticky, paginazione e/o virtual scrolling, evitare layout shift.

### Frontend
- Preferire i pattern del framework in uso (composition API in Vue, hooks in React, ecc.).
- AJAX/fetch centralizzati in service layer.
- WebSocket per aggiornamenti real-time se il framework lo supporta nativamente.
- **Mai** lasciare `console.log()` in produzione.

---

## Regole critiche prima di modificare codice

### Principio fondamentale: il codice esistente funziona
**REGOLA ASSOLUTA**: assumere che il codice esistente sia funzionante.

1. **VERIFICA** prima che il problema esista davvero.
2. **NON modificare** codice esistente per "fixare" problemi causati da nuove funzionalità.
3. **Isola** le nuove funzionalità senza toccare codice esistente.
4. **Se un bug esiste** nel codice esistente, documentalo e risolvilo separatamente con un commit dedicato.

### Verifica sempre prima di modificare
1. **Identifica esattamente la sorgente dati** che il codice usa: in sistemi multi-database o multi-API è facile sbagliare bersaglio.
2. **Non assumere**: se qualcosa sembra rotto, verifica con query/test diretti.
3. **Testa il codice esistente** prima di cambiarlo.
4. **Modifiche minimali**: cambia solo ciò che serve.
5. **Rollback immediato**: se una modifica causa problemi, ripristina subito.

---

## Sistema di protezione del codice esistente

### Zona rossa — NON MODIFICARE senza confronto esplicito
File ad alto rischio (singleton, factory, middleware di autenticazione, router di database, gestione segreti, configurazione globale). In ogni progetto identificare l'elenco e documentarlo (es. in `.cursorrules` o in questo CLAUDE.md).

### Zona gialla — Modificabili con cautela
File core con sezioni delicate: punto di ingresso applicazione, layer dati comune, gestione sessione/token. Modifiche solo dopo aver capito le invarianti.

### Zona verde — Modificabili liberamente
- Nuovi moduli/router/componenti
- Nuovi template/viste
- Nuovi script di utility
- Documentazione

### Pattern anti-loop di debug
**Se nuovo codice rompe qualcosa**: fixa il **NUOVO** codice, non quello esistente.

Pattern preferiti rispetto alla modifica diretta:
1. **Wrapper**: funzione/oggetto che incapsula la chiamata legacy.
2. **Extension**: estendi la classe invece di modificarla.
3. **Feature flag**: nuova funzionalità dietro flag, attivabile per ambiente.
4. **File separato**: nuova logica in nuovo file, registrata accanto all'esistente.
5. **Decorator/middleware**: logica trasversale aggiunta senza toccare gli handler.

---

## Sviluppo di nuovi moduli — Linee guida

1. **Crea la struttura** secondo le convenzioni del progetto (cartelle `modules/`, `routers/`, `services/`, `components/`, `views/` …).
2. **Implementa il layer dati** isolando l'accesso al database/API.
3. **Implementa il layer route/API** con autenticazione e validazione input.
4. **Registra il modulo** nel punto di ingresso (`app.py`, `main.py`, router root, indice componenti).
5. **Aggiungi al menu/navigation** se previsto, rispettando il sistema dei permessi.
6. **Test**: scrivi almeno test minimi sul percorso felice e sugli errori principali.
7. **Documenta**: aggiorna README/CHANGELOG.

### Regole sviluppo moduli
- Moduli completamente separati — nessuna dipendenza circolare.
- Riutilizza codice utile — importa funzioni, non copiare.
- Coerenza grafica — usa componenti e layout esistenti.
- Verifica funzionamento manuale + test automatici prima del commit.

---

## Errori comuni da evitare

### Database / Dati
- **NO**: modificare query senza verificare quale sorgente viene effettivamente usata.
- **NO**: assumere stessa struttura tabella in tutti i database/ambienti.
- **NO**: scrivere su produzione da development.
- **NO**: connessioni database non chiuse.
- **NO**: query SQL senza parametri (SQL injection).

### Configurazione
- **NO**: hardcode di valori configurabili — usa `config.get()` con fallback.
- **NO**: credenziali committate in git.

### Moduli
- **NO**: dipendenze circolari tra moduli.
- **NO**: duplicazione di codice tra moduli.
- **NO**: route/API senza protezione di autenticazione.
- **NO**: verifica permessi solo nel template — sempre anche nel backend.

### Esperienza utente
- **NO**: introdurre stili ad-hoc al di fuori del sistema condiviso senza discussione.
- **NO**: regressioni grafiche su moduli esistenti durante refactor non grafici.

---

## Debugging e Logging

### Pattern logging
Usare il logger del framework/linguaggio in uso, mai `print()` o `console.log()` nel codice di produzione.

```python
import logging
logger = logging.getLogger(__name__)
logger.info("Messaggio informativo")
logger.error("Messaggio errore", exc_info=True)
```

### Regole logging
1. **Mai loggare** credenziali, token, dati sensibili, payload completi con PII.
2. **Usa livelli appropriati** (`debug`, `info`, `warning`, `error`).
3. **MAI lasciare** `debugger`, `pdb.set_trace()`, `breakpoint()`, `console.log` di debug.
4. **Sostituisci** `print()` con `logger.*` prima del commit.
5. **Log rotation** configurata per evitare crescita infinita.

---

## Deploy

### Regole generali
1. **Testa sempre** su sviluppo prima di produzione.
2. **Backup** dello stato (database, configurazioni, volumi) prima di deploy critici.
3. **Verifica** che le configurazioni di produzione siano corrette (URL, secret, target host).
4. **Monitora** i log subito dopo il deploy.
5. **Rollback** sempre disponibile (commit precedente, snapshot, immagine container).

### Container / LXC / VM
- Documenta lo script di installazione (`install.sh`, `Dockerfile`, ecc.) e mantieni il flag di **upgrade** distinto da quello di **fresh install**.
- Distingui chiaramente fra path sorgente e path di installazione: se coincidono, evitare copie distruttive.
- Preserva i dati di stato (database SQLite, file di configurazione utente, chiavi SSH del servizio) durante upgrade.

---

## Gestione `CHANGELOG.md`

**REGOLA OBBLIGATORIA**: ogni modifica rilevante deve essere registrata in `CHANGELOG.md` nella root del progetto. Se il file non esiste, crearlo al primo aggiornamento.

### Quando aggiornare
Aggiornare `CHANGELOG.md` **prima del commit** per:
- **Aggiunte**: nuovi moduli, route, componenti, funzionalità, tabelle/colonne DB.
- **Modifiche**: cambiamenti di comportamento, refactoring visibili, aggiornamenti config, modifiche a permessi/menu.
- **Ottimizzazioni**: miglioramenti performance, query più efficienti, riduzione carico, caching.
- **Correzioni**: bug fix, fix di sicurezza, regressioni, correzioni documentazione.

Modifiche puramente cosmetiche (commenti, spazi bianchi) **non** richiedono voce.

### Formato
Standard [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) con date `YYYY-MM-DD`, raggruppamento per data/versione, lingua coerente con il resto della documentazione del progetto.

```markdown
# Changelog

Tutte le modifiche rilevanti a questo progetto vengono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).

## [Unreleased]

### Aggiunte
- Breve descrizione di cosa è stato aggiunto (`path/al/file`).

### Modifiche
- Cosa è cambiato e perché (riferimento a file/route).

### Ottimizzazioni
- Miglioramento performance X (`path/al/file`).

### Correzioni
- Fix bug Z che causava W (`path/al/file`).
```

### Regole di scrittura
1. Una riga per voce, frase completa.
2. **Citare sempre** i file/moduli coinvolti tra parentesi quando utile.
3. **Non citare** credenziali, IP interni sensibili, dettagli non pubblicabili.
4. **Raggruppare** le voci della stessa data sotto un'unica sezione.
5. **Cronologia**: sezioni più recenti in alto.
6. Se la modifica è documentata altrove, aggiungere il link relativo.

### Workflow operativo
A fine task:
1. Aprire `CHANGELOG.md` (o crearlo).
2. Aggiungere voci nelle categorie appropriate sotto la data odierna.
3. Includere `CHANGELOG.md` nello stesso commit.

---

## Checklist prima del commit

### Verifica pre-modifica
- [ ] Ho capito quale parte del codice tocco e perché?
- [ ] Il file è in zona verde (oppure ho approvazione per gialla/rossa)?
- [ ] Ho verificato che il problema esista davvero nel codice esistente?
- [ ] Ho testato il codice esistente PRIMA di modificarlo?

### Codice
- [ ] Codice testato localmente.
- [ ] Nessun errore di sintassi, type-check, linting.
- [ ] Database: verificato il livello di permesso prima di operazioni di scrittura.
- [ ] Configurazione: nessuna credenziale hardcoded.
- [ ] Autenticazione: route protette correttamente.
- [ ] Moduli: nessuna dipendenza circolare.
- [ ] Grafica: coerente con il design esistente.
- [ ] Log: logging appropriato, nessun `print`/`console.log` di debug residuo.
- [ ] Pattern wrapper/extension usato invece di modificare codice esistente?
- [ ] `CHANGELOG.md` aggiornato.

---

## Principi fondamentali

1. **Modularità**: ogni modulo è indipendente e riutilizzabile.
2. **Sicurezza**: mai scrivere su produzione da development, mai esporre segreti.
3. **Coerenza**: rispetta stile, pattern e design esistenti.
4. **Documentazione**: documenta le modifiche significative.
5. **Testing**: testa sempre prima del commit.
6. **Backup**: backup prima di modifiche importanti.
7. **Performance**: ottimizza query, batch operazioni pesanti, evita N+1.
8. **Reversibilità**: ogni cambio deve essere annullabile facilmente.

---

## Documentazione

### Posizione
Adatta alle convenzioni del progetto:

| Tipo | Posizione tipica |
|------|------------------|
| Documentazione tecnica/architetturale | `docs/`, `docs/handbook/`, `docs/architecture/` |
| Procedure operative (deploy, sync, rollback) | `docs/materiale/`, `docs/operations/`, `runbooks/` |
| Manuale utente | `docs/manuale_utente/`, `docs/user/` |
| Indice / sito statico | `docs/index.md` + generatore (MkDocs, Docusaurus, …) |

### Regole per generazione documenti Markdown
1. **Lingua**: coerente col resto della documentazione del progetto. Termini tecnici (URL, route, tabelle) in forma letterale.
2. **Tono**: chiaro, frasi complete, evitare elenchi telegrafici senza contesto.
3. **Link**: percorsi relativi tra file in `docs/`. URL completi per riferimenti esterni.
4. **Codice**: blocchi fenced con linguaggio (`bash`, `python`, `yaml`, `typescript`). Comandi completi e copiabili.
5. **Segreti**: **mai** password, token, stringhe di connessione reali; usare placeholder o riferimenti ai file di configurazione (senza valori).
6. **Riferimenti al codice**: citare path reali e verificabili nel repo.
7. **Tabelle e titoli**: Markdown standard, gerarchia logica.

### Cosa non fare
- **No** duplicare interi capitoli: meglio un capitolo breve che linka un manuale lungo.
- **No** documentare credenziali o IP/host come "valori fissi" se sono configurabili — riferire la chiave di configurazione.
- **No** suggerire comandi distruttivi (sovrascritture in produzione, `rm -rf`, `git reset --hard` non motivati) senza warning espliciti.

### Checklist nuovo documento
- [ ] Posizione corretta secondo le convenzioni del progetto.
- [ ] Lingua e pubblico definiti (utente finale vs sistemista vs sviluppatore).
- [ ] Link relativi e assenza di segreti.
- [ ] Aggiornamento di indici/`mkdocs.yml`/`sidebar.json` se necessario.
- [ ] Riferimento incrociato dai documenti correlati.

---

## Memoria persistente

Quando disponibile (sistema di memory dell'agente), sfrutta la memoria persistente per:
- Ruolo e preferenze dell'utente.
- Feedback ricorrenti (cosa evitare, cosa replicare).
- Stato di iniziative in corso (deadline, motivazioni, decisioni).
- Riferimenti a sistemi esterni (issue tracker, dashboard, canali).

**Non** memorizzare ciò che è derivabile dal codice o dalla cronologia git.

---

## Rilascio versioni e aggiornamento — dapx-unified

**REGOLA OBBLIGATORIA**: ogni rilascio di una nuova versione di dapx-unified deve seguire **esattamente** questo flusso. Saltare anche un solo passo causa update fantasma (es. UI mostra `X → X` anche dopo pull, vedi incidente v3.11.2 → fix v3.11.3).

### Le 5 versioni da allineare (TUTTE, sempre)

Esistono **cinque** punti dove la versione è scritta. Devono **tutti** essere bumpati allo stesso `X.Y.Z`:

1. **`version.json`** (root del repo) ← letto da `update.sh` e dal backend updater per il confronto remoto/locale. **Saltarlo è l'errore più comune** e produce "X → X" anche dopo update riuscito.
2. **`backend/version.json`**.
3. **`backend/main.py`** — kwarg `FastAPI(version="X.Y.Z", …)`.
4. **`backend/main.py`** — endpoint `/api/health`, campo `"version"` nel dict di risposta (è hardcoded, va aggiornato a mano).
5. **`frontend/package.json`** — campo `"version"`.

Verifica rapida prima del commit:

```bash
grep -rn '"version"' version.json backend/version.json frontend/package.json backend/main.py | grep -v node_modules
```

Tutte le righe devono mostrare la stessa `X.Y.Z`.

### Procedura di rilascio (ordine vincolante)

1. **Bump** delle 5 versioni sopra.
2. **Rebuild frontend**: `cd frontend && npm run build`. Il `frontend/dist/` è git-tracked (lo legge `install.sh` e il fallback di `update.sh` quando npm/Node non sono disponibili sul target). Senza rebuild, l'UI installata resta vecchia anche dopo update.
3. **Aggiornare `CHANGELOG.md`** con la nuova sezione `## [X.Y.Z] - YYYY-MM-DD` e voci nelle categorie `Aggiunte / Modifiche / Ottimizzazioni / Correzioni`.
4. **Commit** con messaggio descrittivo (es. `fix(version): sync root version.json (vX.Y.Z)`), includendo i 5 file di versione + `frontend/dist/` + `CHANGELOG.md`.
5. **Tag**: `git tag vX.Y.Z`.
6. **Push**: `git push origin main --tags`.
7. **GitHub Release** (passo **obbligatorio**, non basta il tag):

   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z — <titolo>" --notes "$(cat <<'EOF'
   ## Correzioni / Aggiunte / Modifiche
   - …
   EOF
   )"
   ```

   **Perché**: la pagina "Aggiornamenti Sistema" del backend usa `https://api.github.com/repos/grandir66/DA-PXREPL/releases/latest`. Senza `gh release create`, l'UI continua a vedere la release precedente anche se il tag esiste.

### Verifica post-rilascio

```bash
gh release list | head -5
curl -s https://api.github.com/repos/grandir66/DA-PXREPL/releases/latest | grep tag_name
curl -s "https://raw.githubusercontent.com/grandir66/DA-PXREPL/main/version.json?t=$(date +%s)"
```

Tutti devono mostrare `vX.Y.Z` / `X.Y.Z`.

### Come funziona l'update lato server

Sul container installato esistono **due** percorsi di aggiornamento, allineati ma distinti:

- **Bottone "Aggiorna" nell'UI** → [`backend/routers/updates.py`](backend/routers/updates.py) `run_update_process()`: `git fetch && git reset --hard origin/main` su `INSTALL_DIR`, poi `pip install -r requirements.txt`, `npm install && npm run build`, restart servizio.
- **Script CLI `update.sh`**: stessa logica, con in più
  - cache-buster su `raw.githubusercontent.com` (`?t=$(date +%s)` + header `Cache-Control: no-cache`) perché il CDN cache 5 minuti dopo un push,
  - **fallback automatico su `frontend/dist` precompilato** se `npm` manca o se la build fallisce (es. Node troppo vecchio per Vite ≥ 7 — serve Node 20.19+ o 22.12+).

Entrambi confrontano il `version.json` di root locale con quello remoto: per questo è **critico** che il file 1 della lista sopra sia sempre allineato.

### Errori da non ripetere

- **NO**: bumpare solo `backend/version.json` o solo `frontend/package.json` "tanto è la stessa cosa". Sono 5 file, non 1.
- **NO**: pushare il tag senza `gh release create`. L'UI continuerà a mostrare la release precedente.
- **NO**: dimenticare il rebuild del `frontend/dist/`. Il fallback di `update.sh` userebbe il dist vecchio del repo e l'UI installata resterebbe alla versione precedente, anche con backend nuovo.
- **NO**: hardcodare versioni in nuovi endpoint/health-check. Se serve, leggere da `version.json` con un helper, non duplicare la stringa.
- **NO**: forzare `git reset --hard` sul server senza prima aver fatto `gh release create`: il pull funziona ma la pagina Updates resta bloccata sulla release vecchia.

### Checklist pre-commit per un rilascio

- [ ] `grep '"version"'` mostra la stessa `X.Y.Z` nei 5 file.
- [ ] `frontend/dist/` rigenerato con la nuova versione.
- [ ] `CHANGELOG.md` ha la sezione `## [X.Y.Z] - YYYY-MM-DD`.
- [ ] Tag `vX.Y.Z` pushato.
- [ ] `gh release create vX.Y.Z` eseguito (verificato con `gh release list`).
- [ ] `curl` su `raw.githubusercontent.com/.../version.json` ritorna `X.Y.Z`.

---

## Layout deterministico, install.sh, update.sh — dapx-unified

**REGOLA OBBLIGATORIA**: il backend in produzione deve stare in `/opt/dapx-unified/backend/`. Niente file Python alla root di `/opt/dapx-unified` (fatta eccezione per `update.sh`, `version.json`, `frontend/`, `_legacy_backup_*`).

### Layout corretto (post v3.17.4)

```
/opt/dapx-unified/
├── backend/          ← codice Python, qui sta WorkingDirectory
│   ├── main.py
│   ├── database.py
│   ├── update_db_schema.py
│   ├── routers/
│   ├── services/
│   └── ...
├── frontend/
│   ├── dist/         ← bundle Vite, servito da FastAPI
│   ├── package.json
│   └── src/          ← presente perché update.sh fa git reset
├── venv/             ← virtualenv condiviso
├── update.sh
└── version.json
```

### Systemd unit: regole

```ini
WorkingDirectory=/opt/dapx-unified/backend
ExecStart=/opt/dapx-unified/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8420 --workers 1
EnvironmentFile=-/etc/dapx-unified/dapx-unified.env
```

`main:app` viene risolto rispetto al `WorkingDirectory`. Se `WorkingDirectory` punta alla root (`/opt/dapx-unified`) e a quella root c'è un `main.py` legacy, Python carica quello e ignora `backend/main.py`. Tutto il backend gira su codice vecchio anche dopo update apparentemente riusciti.

### Database SQLite

Path **assoluto**: `/var/lib/dapx-unified/dapx.db`. Risolto in `backend/database.py`. Il DB **non** sta dentro `/opt/dapx-unified/` — è separato di proposito così che un `git reset --hard` o un re-clone non lo tocchi. Backup automatici giornalieri in `/var/lib/dapx-unified/dapx.db.backup-YYYYMMDDHHMMSS` creati da `update.sh`.

### Schema migrations: le 3 verità da non confondere

1. **`Base.metadata.create_all(bind=engine)`** crea solo tabelle mancanti. **Non** aggiunge colonne nuove a tabelle esistenti.
2. **`update_db_schema.py`** (`_ensure_column` idempotente) è quello che aggiunge colonne ad-hoc. Va eseguito **a ogni update**.
3. **`main.py` lifespan** chiama già `update_schema()` allo startup, ma questo aiuta solo se il backend parte. Se il backend crashava prima di arrivare al lifespan (es. shadowing legacy), le colonne mancano e la situazione è confusa. **`update.sh` deve eseguire `update_db_schema.py` esplicitamente**, ridondante ma deterministico.

### SQLAlchemy 2.x: autobegin (errore corretto in v3.17.4)

```python
# SBAGLIATO (era così fino a 3.17.3):
with engine.connect() as conn:
    trans = conn.begin()   # ← exception: "transaction already initialized"
    ...
    trans.commit()

# GIUSTO (dalla v3.17.4):
with engine.connect() as conn:
    # autobegin è già attivo, niente conn.begin() esplicito
    ...
    conn.commit()
```

In SQLAlchemy 2.x `engine.connect()` apre già la transazione (autobegin). Chiamare `conn.begin()` dopo è un errore.

### Trappola "legacy root layout"

**Sintomo**: dopo un update, alcune feature nuove non funzionano. La UI mostra "API endpoint not found" su rotte che esistono nel codice. `version.json` dice 3.17.X ma il comportamento è di una versione vecchia.

**Causa**: install.sh prima della v3.17.4 copiava `backend/*` direttamente in `/opt/dapx-unified/`, spalmando il backend a root. Quando un update successivo fa `git reset --hard`, l'albero `backend/` del repo viene ricreato accanto ai file legacy. Con `WorkingDirectory=/opt/dapx-unified` e `main:app`, Python carica `/opt/dapx-unified/main.py` (legacy non-tracked) invece di `/opt/dapx-unified/backend/main.py` (tracked corrente).

**Fix automatico**: `update.sh` dalla v3.17.4 rileva il layout legacy (presenza simultanea di `main.py` + `routers/` + `backend/` alla root) e sposta i file legacy in `_legacy_backup_TIMESTAMP/` PRIMA del git pull. Aggiorna anche il `WorkingDirectory` del unit con `sed`.

**Fix manuale** (per installazioni rotte che non passano via `update.sh`):

```bash
BK=/opt/dapx-unified/_legacy_backup_$(date +%Y%m%d%H%M%S)
mkdir -p "$BK"
mv /opt/dapx-unified/{main.py,database.py,update_db_schema.py,routers,services} "$BK/"
sed -i 's|^WorkingDirectory=/opt/dapx-unified$|WorkingDirectory=/opt/dapx-unified/backend|' /etc/systemd/system/dapx-unified.service
systemctl daemon-reload
systemctl restart dapx-unified
cd /opt/dapx-unified/backend && /opt/dapx-unified/venv/bin/python3 update_db_schema.py
```

### Errori da non ripetere (lezioni dalla sessione 2026-05-04)

- **NO**: copiare il backend con `cp -r backend/* $INSTALL_DIR/`. Sempre `cp -r backend/ $INSTALL_DIR/backend/`. Il glob `backend/*` spalma e crea il bug di shadowing futuro.
- **NO**: assumere che "version.json dice 3.17.X" implichi "il codice 3.17.X gira". `version.json` è solo un file dati, non riflette il codice in esecuzione. Per verificare cosa gira davvero: `curl /openapi.json` e cerca le route nuove.
- **NO**: attribuire un 404 a "browser cache" senza prima controllare `/openapi.json`. Se OpenAPI non ha la route, è un problema di backend, non di cache.
- **NO**: fare `git reset --hard` senza chiedersi se ci sono file non-tracked sospetti alla root. Sospetto: file Python alla root quando il repo li ha in `backend/`.
- **NO**: spostare cartelle/file su un'installazione live senza verificare prima che il DB stia altrove (`/var/lib/...`) e che non venga incluso nello spostamento.
- **NO**: lanciare comandi multi-riga via blocchi paste in terminali con bracketed paste mode acceso (`^[[200~`). Se il prompt mostra `^[[200~`, eseguire `printf '\e[?2004l'` prima di reincollare.
- **NO**: cercare `__pycache__` come fonte di stale solo dopo aver provato 3 restart. È sempre la prima cosa da pulire dopo un'operazione invasiva sui file Python.
- **NO**: fidarsi del `MainPID` di systemd come prova che gira il codice giusto. Verifica con `ls -la /proc/$PID/cwd`.

### Checklist post-update (verifica deterministica)

```bash
# 1. layout corretto
test -f /opt/dapx-unified/backend/main.py && echo "backend OK" || echo "BACKEND MANCA"
test -f /opt/dapx-unified/main.py && echo "ATTENZIONE: legacy main.py ancora presente" || echo "no legacy"

# 2. unit corretto
grep WorkingDirectory /etc/systemd/system/dapx-unified.service
# atteso: WorkingDirectory=/opt/dapx-unified/backend

# 3. backend gira sul codice giusto
PID=$(systemctl show -p MainPID dapx-unified | cut -d= -f2)
ls -la /proc/$PID/cwd
# atteso: -> /opt/dapx-unified/backend

# 4. tutte le route nuove sono registrate
curl -s http://localhost:8420/openapi.json | python3 -c "
import sys,json
paths = list(json.load(sys.stdin)['paths'])
expected = ['/api/sync-jobs/', '/api/pve-replication/', '/api/updates/changelog']
for e in expected:
    print(e, 'OK' if any(e in p for p in paths) else 'MISSING')
"

# 5. schema DB ha le colonne nuove
/opt/dapx-unified/venv/bin/python3 -c "
import sqlite3
cols = [c[1] for c in sqlite3.connect('/var/lib/dapx-unified/dapx.db').execute('PRAGMA table_info(sync_jobs)').fetchall()]
for needed in ('dest_bridge','dest_vlan','dump_dir','pve_compress','replace_existing'):
    print(needed, 'OK' if needed in cols else 'MISSING')
"
```

Se uno di questi check fallisce, **non dichiarare l'update completato**.

---

*Documento universale — adattare alle convenzioni specifiche del progetto leggendone `README.md`, file di configurazione e codice prima di operare.*
