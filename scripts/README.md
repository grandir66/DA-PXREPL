# Scripts operativi

Layout del repository **dapx-unified** (unico progetto attivo; il vecchio `dapx-backandrepl` è fuori da questo git).

| Percorso | Uso |
|----------|-----|
| `scripts/` | Manutenzione, catch-up, deploy beta, cleanup CT produzione |
| `scripts/dev/` | Sviluppo locale (`run_dev.py`) |
| `backend/scripts/` | **Runtime API** — invocati dal backend (cert SSL, diagnostica nodi, verify DB). Non spostare senza aggiornare i router. |
| `backend/services/proxlb_lib/` | Libreria vendored ProxLB per load balancer (non repo annidato) |

## Script principali

- `catchup_vm_groups.py` / `run_catchup.sh` — recupero manuale gruppi VM
- `cleanup_production_layout.sh` — archivia file legacy non tracciati su CT
- `db_maintenance.py` — pulizia log DB
- `cleanup_production_layout.sh` — archivia file legacy non tracciati su CT

I vecchi script di debug one-off sono stati rimossi; usare i log di sistema e le API diagnostiche dei nodi.
