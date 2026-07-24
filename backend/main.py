"""
DAPX-Unified - Backend API
Sistema centralizzato di backup e replica per infrastrutture Proxmox
Con autenticazione integrata Proxmox VE
# Supporta replica ZFS (Sanoid/Syncoid), BTRFS e PBS (Proxmox Backup Server)
"""

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
import os
import logging

from database import engine, Base, get_db, init_default_config, SessionLocal
from routers import nodes, snapshots, sync_jobs, vms, logs, settings, auth, ssh_keys
from routers import recovery_jobs, backup_jobs, host_info, host_backup, migration_jobs, updates, pve_replication_jobs
from routers import ha, clusters
from routers import file_endpoints, file_replication_jobs
from routers import nas_sync_jobs
from routers import vm_snapshot_jobs
from routers import schedule as schedule_router
from services.scheduler import scheduler_service
from services.logging_config import setup_logging, get_logger

# Configurazione logging avanzato
# Variabili ambiente supportate:
#   DAPX_LOG_LEVEL: DEBUG, INFO, WARNING, ERROR (default: INFO)
#   DAPX_LOG_DIR: directory per file di log (default: /var/log/dapx-backandrepl)
#   DAPX_LOG_VERBOSE: true/false per log extra verbosi
setup_logging(
    console_output=True,
    file_output=True,
    json_output=False
)
logger = get_logger(__name__)

# Scheduler: UNA sola istanza condivisa (il singleton usato da router/servizi).
# Costruire un secondo SchedulerService() qui creerebbe un'istanza morta su cui
# update/remove/lock non avrebbero effetto (bug C-01/B1).
scheduler = scheduler_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestione lifecycle dell'applicazione"""
    # Startup
    logger.info("Avvio DAPX-backandrepl...")
    Base.metadata.create_all(bind=engine)

    # Migrazioni leggere idempotenti: aggiunge le colonne nuove alle
    # tabelle esistenti (SQLite non le crea automaticamente).
    try:
        from update_db_schema import update_schema
        update_schema()
        app.state.schema_error = None
    except Exception as e:
        # C-09: non più silenzioso a warning — è un problema strutturale che va
        # visto (log ERROR) e segnalato in /api/health, così un endpoint che poi
        # fallisce per colonna mancante è correlabile subito.
        logger.error(f"update_db_schema FALLITO (schema potenzialmente incompleto): {e}", exc_info=True)
        app.state.schema_error = str(e)

    try:
        from services.nas_sync.execution import reconcile_stale_running_jobs as _nas2_reconcile
        _nas2_reconcile()
    except Exception as _exc:  # noqa: BLE001 — il reconcile non deve bloccare l'avvio
        logger.warning(f"nas_sync reconcile all'avvio fallito: {_exc}")

    try:
        from services.vm_snapshot.execution import reconcile_stale_running_jobs as _vmsnap_reconcile
        _vmsnap_reconcile()
    except Exception as _exc:  # noqa: BLE001 — il reconcile non deve bloccare l'avvio
        logger.warning(f"vm_snapshot reconcile all'avvio fallito: {_exc}")

    # Inizializza configurazione di default
    db = SessionLocal()
    try:
        init_default_config(db)
    finally:
        db.close()
    
    await scheduler.start()
    logger.info("DAPX-backandrepl avviato")
    
    yield
    
    # Shutdown
    logger.info("Arresto DAPX-backandrepl...")
    await scheduler.stop()
    logger.info("DAPX-backandrepl arrestato")


app = FastAPI(
    title="DAPX-backandrepl",
    description="Sistema centralizzato di backup e replica per Proxmox VE. Supporta ZFS (Sanoid/Syncoid), BTRFS (btrfs send/receive) e PBS (Proxmox Backup Server).",
    version="3.18.1",
    lifespan=lifespan
)


# CORS configurato correttamente
_cors_raw = os.environ.get("DAPX_CORS_ORIGINS") or os.environ.get("SANOID_MANAGER_CORS_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    # Default: stesso host
    ALLOWED_ORIGINS = ["http://localhost:8420", "http://127.0.0.1:8420"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)


# Exception handler globale.
# In produzione (DAPX_ENV != "dev") nasconde il detail; in dev espone il
# tipo di eccezione + messaggio per facilitare il debug. Lo stack trace
# completo va sempre nei file di log.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception su {request.method} {request.url.path}: {exc}", exc_info=True)
    is_dev = os.environ.get("DAPX_ENV", "production").lower() in ("dev", "development", "local")
    detail = (
        f"{type(exc).__name__}: {exc}" if is_dev else "Errore interno del server"
    )
    return JSONResponse(status_code=500, content={"detail": detail})





# Router API
dapx_mode = os.environ.get("DAPX_MODE", "full")
if dapx_mode == "lb":
    dapx_mode = "full"

# Core Routers (available in all modes)
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["Nodes"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(logs.router, prefix="/api/logs", tags=["Logs"])
app.include_router(ssh_keys.router, prefix="/api", tags=["SSH Keys"])
app.include_router(host_info.router, prefix="/api", tags=["Host Info & Dashboard"])
app.include_router(updates.router, tags=["Updates"])
app.include_router(ha.router, prefix="/api/ha", tags=["High Availability & Cluster"])
app.include_router(clusters.router, tags=["Clusters"])

# Conditionally include Configuration Backup (useful in both, but maybe simpler in LB mode?)
# We keep it in both for now as it backs up the DB/Config
from routers import config_backup
app.include_router(config_backup.router, tags=["Configuration Backup"])

# Full Mode Only Routers
if dapx_mode == "full":
    app.include_router(snapshots.router, prefix="/api/snapshots", tags=["Snapshots"])
    app.include_router(sync_jobs.router, prefix="/api/sync-jobs", tags=["Sync Jobs"])
    app.include_router(backup_jobs.router, prefix="/api/backup-jobs", tags=["Backup Jobs (PBS)"])
    app.include_router(recovery_jobs.router, prefix="/api/recovery-jobs", tags=["Recovery Jobs (PBS)"])
    app.include_router(vms.router, prefix="/api/vms", tags=["VMs"])
    app.include_router(host_backup.router, prefix="/api/host-backup", tags=["Host Config Backup"])
    app.include_router(migration_jobs.router, prefix="/api/migration-jobs", tags=["Migration Jobs"])
    app.include_router(pve_replication_jobs.router, prefix="/api/pve-replication", tags=["PVE Replication"])
    app.include_router(file_endpoints.router, prefix="/api/file-endpoints", tags=["File Endpoints"])
    app.include_router(file_replication_jobs.router, prefix="/api/file-replication", tags=["File Replication"])
    app.include_router(nas_sync_jobs.router, prefix="/api/nas-sync", tags=["Repliche dati (NAS Sync v2)"])
    app.include_router(vm_snapshot_jobs.router, prefix="/api/vm-snapshots", tags=["Snapshot VM"])
    app.include_router(schedule_router.router, prefix="/api/schedule", tags=["Schedule"])


# Health check (non richiede autenticazione).
# Verifica DB + scheduler vivo. Ritorna 503 se uno dei controlli fallisce
# (utile per liveness probe / monitoring esterno).
@app.get("/api/health")
async def health_check():
    from sqlalchemy import text as _sql_text
    from datetime import datetime as _dt
    payload: dict = {
        "status": "healthy",
        "version": "3.18.1",
        "auth_enabled": True,
        "mode": dapx_mode,
        "checks": {},
        "features": ["zfs", "btrfs", "pbs", "ha", "cluster", "nas-sync", "vm-snapshots"] if dapx_mode == "full" else [],
        "ts": _dt.utcnow().isoformat() + "Z",
    }
    healthy = True
    # DB ping
    try:
        db = SessionLocal()
        try:
            db.execute(_sql_text("SELECT 1"))
            payload["checks"]["db"] = "ok"
        finally:
            db.close()
    except Exception as e:
        payload["checks"]["db"] = f"error: {type(e).__name__}"
        healthy = False
    # Scheduler vivo
    try:
        if scheduler and getattr(scheduler, "_running", False):
            payload["checks"]["scheduler"] = "running"
        else:
            payload["checks"]["scheduler"] = "stopped"
            healthy = False
    except Exception as e:
        payload["checks"]["scheduler"] = f"error: {type(e).__name__}"
        healthy = False
    # Schema DB: se la migrazione allo startup è fallita, segnalalo (C-09).
    schema_err = getattr(app.state, "schema_error", None)
    payload["checks"]["schema"] = "ok" if not schema_err else f"error: {schema_err[:120]}"

    if not healthy:
        payload["status"] = "degraded"
        return JSONResponse(status_code=503, content=payload)
    return payload


# Setup check (verifica se è necessario il setup iniziale)
@app.get("/api/setup-required")
async def setup_required(db=Depends(get_db)):
    from database import User
    user_count = db.query(User).count()
    return {"setup_required": user_count == 0}


# Serve static files (frontend)
# Prova diversi percorsi possibili per il frontend
possible_frontend_paths = [
    os.path.join(os.path.dirname(__file__), "frontend", "dist"),
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"),
    "/opt/dapx-unified/frontend/dist",
    "/opt/sanoid-manager/frontend/dist",  # legacy install path
]

frontend_path = None
for path in possible_frontend_paths:
    if os.path.exists(path) and os.path.isfile(os.path.join(path, "index.html")):
        frontend_path = path
        logger.info(f"Frontend trovato in: {frontend_path}")
        break

if frontend_path:
    # /assets/* contiene i chunk Vite con hash nel nome (es.
    # index-CURHmSzy.js): immutabili, possono essere cachati a lungo.
    # Il problema "vecchia UI dopo update" sta su index.html (no hash),
    # quindi quello va servito sempre con no-cache.
    assets_path = os.path.join(frontend_path, "assets")
    if os.path.exists(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

    _NO_CACHE_HEADERS = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    @app.get("/")
    async def serve_frontend():
        return FileResponse(
            os.path.join(frontend_path, "index.html"),
            headers=_NO_CACHE_HEADERS,
        )

    @app.get("/{full_path:path}")
    async def catch_all(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        # Anti path-traversal: il file risolto deve stare sotto frontend_path.
        file_path = os.path.realpath(os.path.join(frontend_path, full_path))
        _fp_root = os.path.realpath(frontend_path)
        if (
            os.path.commonpath([_fp_root, file_path]) == _fp_root
            and os.path.exists(file_path)
            and os.path.isfile(file_path)
        ):
            return FileResponse(file_path, headers=_NO_CACHE_HEADERS)

        return FileResponse(
            os.path.join(frontend_path, "index.html"),
            headers=_NO_CACHE_HEADERS,
        )
else:
    logger.warning("Frontend non trovato! L'interfaccia web non sarà disponibile.")
    logger.warning(f"Percorsi cercati: {possible_frontend_paths}")
    
    @app.get("/")
    async def no_frontend():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Frontend non disponibile",
                "message": "L'interfaccia web non è stata trovata. Usa l'API direttamente.",
                "api_docs": "/docs"
            }
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DAPX_PORT") or os.environ.get("SANOID_MANAGER_PORT", 8420))
    # Auto-disable reload if running on non-standard port (e.g. Beta)
    should_reload = port == 8420
    
    # Reload dirs (monitor specific directories if needed, or default)
    # uvicorn.run detects changes in sys.path mainly
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=should_reload)
