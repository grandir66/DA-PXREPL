---
paths:
  - "backend/**"
  - "scripts/**"
---
# Backend: moduli, database, autenticazione, configurazione, logging

> Estratto **parola per parola** da `CLAUDE.md` il 2026-10-01: si carica da solo quando si tocca quest'area. Le regole valgono come prima. Versione intera in git fino a `5653138`.

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

## Configurazione

### Regole
1. **YAML/JSON/ENV preferito su valori hardcoded** — usare `config.get(key, default)` con fallback.
2. **Mai committare** credenziali, token, chiavi private in git. Usare `.env`, secret manager o file `*.local.*` ignorati da git.
3. **File di override per ambiente** (es. `*.production.yaml`) per differenziare dev/staging/prod.
4. **Validare** i valori letti da configurazione (tipo, range, presenza).
5. **Documentare** le variabili di configurazione (es. `config.env.example`, `.env.example`).

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
