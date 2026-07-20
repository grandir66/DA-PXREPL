"""Router CRUD e azioni job Repliche dati v2 (/api/nas-sync)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import FileEndpoint, JobLog, get_db
from routers.auth import User, get_current_user, require_operator
from services.file_replication.path_utils import compact_source_paths
from services.nas_sync.capabilities import resolve_capabilities, resolve_engine
from services.nas_sync.du_catalog import (
    get_catalog_progress,
    refresh_job_du_catalog,
)
from services.nas_sync.execution import (
    execute_nas_sync_job,
    get_job_progress,
    is_job_busy,
    stop_nas_sync_job,
)
from services.nas_sync.models import NasSyncJob
from services.nas_sync.preflight import run_preflight
from services.nas_sync.schemas import NasSyncJobCreate, NasSyncJobOut, NasSyncJobUpdate
from services.nas_sync.state import catalog_summary
from services.scheduler import scheduler_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _latest_log_errors(db: Session, job_ids: list[int]) -> dict[int, str]:
    if not job_ids:
        return {}
    logs = (
        db.query(JobLog)
        .filter(JobLog.job_type == "nas_sync", JobLog.job_id.in_(job_ids))
        .order_by(JobLog.job_id, JobLog.id.desc())
        .all()
    )
    latest: dict[int, JobLog] = {}
    for log in logs:
        latest.setdefault(log.job_id, log)
    return {
        jid: (log.error or log.message or "")
        for jid, log in latest.items()
        if log.status == "failed"
    }


def _engine_info(db: Session, job: NasSyncJob) -> tuple[Optional[str], Optional[str]]:
    source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
    dest = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
    if not source or not dest:
        return None, None
    try:
        return resolve_engine(job.sync_method or "auto", source, dest)
    except ValueError as exc:
        return None, str(exc)


def _job_out(db: Session, job: NasSyncJob, last_run_error: Optional[str] = None) -> NasSyncJobOut:
    engine, reason = _engine_info(db, job)
    src = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
    dst = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
    return NasSyncJobOut(
        id=job.id,
        name=job.name,
        description=job.description,
        source_endpoint_id=job.source_endpoint_id,
        dest_endpoint_id=job.dest_endpoint_id,
        source_paths=job.source_paths or [],
        dest_base_path=job.dest_base_path,
        sync_method=job.sync_method or "auto",
        resolved_engine=job.resolved_engine or engine,
        engine_reason=reason,
        delete_on_dest=bool(job.delete_on_dest),
        rclone_size_only=bool(job.rclone_size_only),
        exclude_presets=job.exclude_presets or [],
        exclude_patterns=job.exclude_patterns or [],
        bandwidth_limit_kb=job.bandwidth_limit_kb,
        snapshot_policy_hint=job.snapshot_policy_hint,
        schedule=job.schedule,
        schedule_config=job.schedule_config,
        is_active=bool(job.is_active),
        current_status=job.current_status,
        last_run_at=job.last_run_at,
        last_run_status=job.last_run_status,
        last_run_duration_sec=job.last_run_duration_sec,
        last_bytes_transferred=job.last_bytes_transferred,
        last_files_transferred=job.last_files_transferred,
        next_run_at=job.next_run_at,
        notify_mode=job.notify_mode,
        notify_subject=job.notify_subject,
        source_endpoint_name=src.name if src else None,
        dest_endpoint_name=dst.name if dst else None,
        last_run_error=last_run_error,
        **catalog_summary(job.run_state or {}),
    )


def _validate_endpoints(db: Session, source_id: int, dest_id: int) -> tuple[FileEndpoint, FileEndpoint]:
    source = db.query(FileEndpoint).filter(FileEndpoint.id == source_id).first()
    dest = db.query(FileEndpoint).filter(FileEndpoint.id == dest_id).first()
    if not source:
        raise HTTPException(status_code=400, detail="Endpoint sorgente non trovato")
    if not dest:
        raise HTTPException(status_code=400, detail="Endpoint destinazione non trovato")
    caps = resolve_capabilities(dest)
    if not caps["rsync_dest"] and not caps["smb"]:
        raise HTTPException(
            status_code=400,
            detail="L'endpoint destinazione non ha capacità valide (né rsync né SMB)",
        )
    return source, dest


@router.get("/stats/summary")
def stats_summary(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    total = db.query(NasSyncJob).count()
    active = db.query(NasSyncJob).filter(NasSyncJob.is_active == True).count()  # noqa: E712
    running = db.query(NasSyncJob).filter(NasSyncJob.current_status == "running").count()
    paused = db.query(NasSyncJob).filter(NasSyncJob.current_status == "paused").count()
    failed = db.query(NasSyncJob).filter(NasSyncJob.last_run_status == "failed").count()
    return {"total": total, "active": active, "running": running, "paused": paused, "failed": failed}


@router.get("/endpoints/{endpoint_id}/capabilities")
def endpoint_capabilities(
    endpoint_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    ep = db.query(FileEndpoint).filter(FileEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint non trovato")
    return resolve_capabilities(ep)


@router.get("", response_model=list[NasSyncJobOut])
def list_jobs(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    jobs = db.query(NasSyncJob).order_by(NasSyncJob.name).all()
    errors = _latest_log_errors(db, [j.id for j in jobs])
    return [
        _job_out(db, j, None if j.current_status == "running" else errors.get(j.id))
        for j in jobs
    ]


@router.post("", response_model=NasSyncJobOut)
def create_job(
    body: NasSyncJobCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    source, dest = _validate_endpoints(db, body.source_endpoint_id, body.dest_endpoint_id)
    try:
        engine, _ = resolve_engine(body.sync_method, source, dest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = NasSyncJob(
        name=body.name,
        description=body.description,
        source_endpoint_id=body.source_endpoint_id,
        dest_endpoint_id=body.dest_endpoint_id,
        source_paths=compact_source_paths(body.source_paths),
        dest_base_path=body.dest_base_path.strip() or "/",
        sync_method=body.sync_method,
        resolved_engine=engine,
        delete_on_dest=body.delete_on_dest,
        rclone_size_only=body.rclone_size_only,
        exclude_presets=body.exclude_presets,
        exclude_patterns=body.exclude_patterns,
        bandwidth_limit_kb=body.bandwidth_limit_kb,
        snapshot_policy_hint=body.snapshot_policy_hint or {},
        schedule=body.schedule,
        schedule_config=body.schedule_config,
        is_active=body.is_active,
        notify_mode=body.notify_mode,
        notify_subject=body.notify_subject,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    if job.schedule and job.is_active:
        scheduler_service.update_nas_sync_schedule(job.id, job.schedule)
    return _job_out(db, job)


@router.get("/{job_id}", response_model=NasSyncJobOut)
def get_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return _job_out(db, job)


@router.put("/{job_id}", response_model=NasSyncJobOut)
def update_job(
    job_id: int,
    body: NasSyncJobUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    data = body.model_dump(exclude_unset=True)
    if data.get("source_paths") is not None:
        data["source_paths"] = compact_source_paths(data["source_paths"])
    for key, value in data.items():
        setattr(job, key, value)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    if job.schedule and job.is_active:
        scheduler_service.update_nas_sync_schedule(job.id, job.schedule)
    else:
        scheduler_service.remove_nas_sync_schedule(job.id)
    return _job_out(db, job)


@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    scheduler_service.remove_nas_sync_schedule(job.id)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.post("/{job_id}/run")
async def run_job(
    job_id: int,
    fresh: bool = Query(False, description="Ignora checkpoint e riparti da capo"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    if is_job_busy(job_id) or job.current_status == "running":
        raise HTTPException(status_code=409, detail="Job già in esecuzione o catalogo in aggiornamento")
    asyncio.create_task(execute_nas_sync_job(job_id, fresh=fresh))
    if fresh:
        message = "Esecuzione avviata da capo"
    elif job.current_status == "paused":
        message = "Ripresa esecuzione dal checkpoint"
    else:
        message = "Esecuzione avviata"
    return {"ok": True, "message": message}


@router.post("/{job_id}/stop")
async def stop_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    result = await stop_nas_sync_job(job_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("message", "Job non in esecuzione"))
    return result


@router.post("/{job_id}/toggle", response_model=NasSyncJobOut)
def toggle_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    job.is_active = not job.is_active
    db.commit()
    db.refresh(job)
    if job.is_active and job.schedule:
        scheduler_service.update_nas_sync_schedule(job.id, job.schedule)
    else:
        scheduler_service.remove_nas_sync_schedule(job.id)
    return _job_out(db, job)


@router.post("/{job_id}/refresh-catalog")
async def refresh_catalog(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    if is_job_busy(job_id):
        raise HTTPException(status_code=409, detail="Replica o catalogo già in corso")
    source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
    if not source:
        raise HTTPException(status_code=400, detail="Endpoint sorgente mancante")
    caps = resolve_capabilities(source)
    if not caps["rsync_source"]:
        raise HTTPException(
            status_code=400,
            detail="Il catalogo du richiede SSH sulla sorgente (non disponibile per questo endpoint)",
        )
    asyncio.create_task(refresh_job_du_catalog(job_id))
    return {"ok": True, "message": "Aggiornamento catalogo du avviato"}


@router.post("/{job_id}/preflight")
async def preflight(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
    dest = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
    if not source or not dest:
        raise HTTPException(status_code=400, detail="Endpoint mancante")
    return await run_preflight(job, source, dest)


@router.get("/{job_id}/logs")
def job_logs(job_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    logs = (
        db.query(JobLog)
        .filter(JobLog.job_type == "nas_sync", JobLog.job_id == job_id)
        .order_by(JobLog.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": log.id,
            "status": log.status,
            "message": log.message,
            "output": log.output,
            "error": log.error,
            "duration": log.duration,
            "transferred": log.transferred,
            "created_at": log.started_at,
            "completed_at": log.completed_at,
        }
        for log in logs
    ]


@router.get("/{job_id}/progress")
def job_progress(job_id: int, _user: User = Depends(get_current_user)):
    prog = get_job_progress(job_id)
    if prog:
        return prog
    cat = get_catalog_progress(job_id)
    if cat:
        return cat
    return {"status": "idle"}
