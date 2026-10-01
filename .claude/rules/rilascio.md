---
paths:
  - "version.json"
  - "backend/version.json"
  - "backend/main.py"
  - "frontend/package.json"
  - "frontend/dist/**"
  - "update.sh"
  - "backend/routers/updates.py"
---
# Rilascio versioni e aggiornamento — dapx-unified

> Estratto **parola per parola** da `CLAUDE.md` il 2026-10-01: si carica da solo quando si tocca quest'area. Le regole valgono come prima. Versione intera in git fino a `5653138`.

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
- **NO**: fermarsi al commit di release senza tag né `gh release create` (v3.21.0, 8 settembre 2026): l'appliance legge `version.json` dal codice pullato e la release da GitHub, quindi si ritrova «installata 3.21.0 → ultima 3.20.16». Il rilascio finisce al passo 7, non al 4.
- **NO**: dimenticare il rebuild del `frontend/dist/`. Il fallback di `update.sh` userebbe il dist vecchio del repo e l'UI installata resterebbe alla versione precedente, anche con backend nuovo.
- **NO**: hardcodare versioni in nuovi endpoint/health-check. Se serve, leggere da `version.json` con un helper, non duplicare la stringa.
- **NO**: forzare `git reset --hard` sul server senza prima aver fatto `gh release create`: il pull funziona ma la pagina Updates resta bloccata sulla release vecchia.

### Checklist pre-commit per un rilascio

- [ ] **`git branch --show-current` dice `main`.** Il repo ha tre worktree e
      rami di lavoro allineati a `main`: un commit di release su un ramo
      qualsiasi si pusha, si taggia e non arriva mai su `main` (8 settembre
      2026, v3.21.1 nata su `restyle-notifiche`).
- [ ] `grep '"version"'` mostra la stessa `X.Y.Z` nei 5 file.
- [ ] `frontend/dist/` rigenerato con la nuova versione.
- [ ] `CHANGELOG.md` ha la sezione `## [X.Y.Z] - YYYY-MM-DD`.
- [ ] Tag `vX.Y.Z` pushato.
- [ ] `gh release create vX.Y.Z` eseguito (verificato con `gh release list`).
- [ ] `curl` su `raw.githubusercontent.com/.../version.json` ritorna `X.Y.Z`.
