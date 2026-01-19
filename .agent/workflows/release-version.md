---
description: Come rilasciare una nuova versione di DA-PXREPL
---

# Rilascio Nuova Versione DA-PXREPL

Quando si effettuano modifiche significative e si vuole rilasciare una nuova versione:

## 1. Aggiornare i file di versione

Ci sono 3 file da aggiornare con la nuova versione:

```bash
# Root version.json
version.json

# Backend version.json  
backend/version.json

# Health check in main.py (cerca "version":)
backend/main.py
```

## 2. Commit e Push

```bash
cd /Users/riccardo/Progetti/DA-PXREPL/dapx-unified
git add -A
git commit -m "vX.Y.Z: Descrizione delle modifiche"
git push origin main
# Se si usa feature branch:
git checkout feature/load-balancer && git merge main && git push origin feature/load-balancer
```

## 3. Creare e Pushare il Tag

**IMPORTANTE**: Il sistema di update cerca i **tags** su GitHub, non i semplici commit!

// turbo
```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

## 4. Verificare su GitHub

Controlla che il tag sia visibile su: https://github.com/grandir66/DA-PXREPL/tags

## 5. Update sul Server

L'utente può ora cliccare "Verifica Aggiornamenti" nella UI e vedere la nuova versione disponibile.

---

## Schema Versioning

- **Major (X)**: Cambiamenti breaking o riscritture significative
- **Minor (Y)**: Nuove funzionalità
- **Patch (Z)**: Bug fix e piccoli miglioramenti

Esempi:
- 3.9.0 → 3.9.1 (patch: fix bug)
- 3.9.1 → 3.10.0 (minor: nuova feature HA)
- 3.10.0 → 4.0.0 (major: riscrittura)
