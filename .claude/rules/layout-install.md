---
paths:
  - "install.sh"
  - "update.sh"
  - "Dockerfile"
  - "docker-compose.yml"
  - "deploy_lxc.sh"
  - "backend/database.py"
  - "backend/update_db_schema.py"
  - "scripts/cleanup_production_layout.sh"
---
# Layout deterministico, install.sh, update.sh

> Estratto **parola per parola** da `CLAUDE.md` il 2026-10-01: si carica da solo quando si tocca quest'area. Le regole valgono come prima. Versione intera in git fino a `5653138`.

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
