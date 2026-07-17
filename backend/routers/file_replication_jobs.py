"""Router CRUD job replica file."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import FileEndpoint, FileEndpointType, FileReplicationJob, JobLog, get_db
from routers.auth import User, get_current_user, require_operator
from services.file_replication.file_replication_execution import (
    execute_file_replication_job,
    get_job_progress,
    is_job_running,
)
from services.file_replication.path_utils import sanitize_path
from services.file_replication_schemas import (
    FileReplicationJobCreate,
    FileReplicationJobOut,
    FileReplicationJobUpdate,
)
from services.scheduler import scheduler_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _job_out(job: FileReplicationJob) -> FileReplicationJobOut:
    hint = job.snapshot_policy_hint
    if hasattr(hint, "model_dump"):
        hint = hint.model_dump()
    return FileReplicationJobOut(
        id=job.id,
        name=job.name,
        description=job.description,
        source_endpoint_id=job.source_endpoint_id,
        dest_endpoint_id=job.dest_endpoint_id,
        source_paths=job.source_paths or [],
        dest_staging_path=job.dest_staging_path,
        sync_method=job.sync_method,
        delete_on_dest=job.delete_on_dest,
        on_source_delete=job.on_source_delete,
        exclude_presets=job.exclude_presets or [],
        exclude_patterns=job.exclude_patterns or [],
        bandwidth_limit_kb=job.bandwidth_limit_kb,
        immutability_strategy=job.immutability_strategy,
        snapshot_policy_hint=hint,
        schedule=job.schedule,
        schedule_config=job.schedule_config,
        is_active=job.is_active,
        current_status=job.current_status,
        last_run_at=job.last_run_at,
        last_run_status=job.last_run_status,
        last_run_duration_sec=job.last_run_duration_sec,
        last_bytes_transferred=job.last_bytes_transferred,
        last_files_transferred=job.last_files_transferred,
        next_run_at=job.next_run_at,
        notify_mode=job.notify_mode,
        notify_subject=job.notify_subject,
        source_endpoint_name=job.source_endpoint.name if job.source_endpoint else None,
        dest_endpoint_name=job.dest_endpoint.name if job.dest_endpoint else None,
    )


def _validate_job_endpoints(db: Session, source_id: int, dest_id: int) -> tuple[FileEndpoint, FileEndpoint]:
    source = db.query(FileEndpoint).filter(FileEndpoint.id == source_id).first()
    dest = db.query(FileEndpoint).filter(FileEndpoint.id == dest_id).first()
    if not source:
        raise HTTPException(status_code=400, detail="Endpoint sorgente non trovato")
    if not dest:
        raise HTTPException(status_code=400, detail="Endpoint destinazione non trovato")
    if dest.endpoint_type != FileEndpointType.QNAP:
        raise HTTPException(status_code=400, detail="La destinazione deve essere QNAP QuTS hero")
    return source, dest


@router.get("/stats/summary")
def stats_summary(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    total = db.query(FileReplicationJob).count()
    active = db.query(FileReplicationJob).filter(FileReplicationJob.is_active == True).count()
    running = db.query(FileReplicationJob).filter(FileReplicationJob.current_status == "running").count()
    failed = db.query(FileReplicationJob).filter(FileReplicationJob.last_run_status == "failed").count()
    return {"total": total, "active": active, "running": running, "failed": failed}


@router.get("", response_model=list[FileReplicationJobOut])
def list_jobs(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    jobs = db.query(FileReplicationJob).order_by(FileReplicationJob.name).all()
    return [_job_out(j) for j in jobs]


@router.post("", response_model=FileReplicationJobOut)
def create_job(
    body: FileReplicationJobCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    _validate_job_endpoints(db, body.source_endpoint_id, body.dest_endpoint_id)
    try:
        dest_path = sanitize_path(body.dest_staging_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    hint = body.snapshot_policy_hint.model_dump() if body.snapshot_policy_hint else {}
    job = FileReplicationJob(
        name=body.name,
        description=body.description,
        source_endpoint_id=body.source_endpoint_id,
        dest_endpoint_id=body.dest_endpoint_id,
        source_paths=[sanitize_path(p) for p in body.source_paths],
        dest_staging_path=dest_path,
        sync_method=body.sync_method,
        delete_on_dest=body.delete_on_dest,
        on_source_delete=body.on_source_delete,
        exclude_presets=body.exclude_presets,
        exclude_patterns=body.exclude_patterns,
        bandwidth_limit_kb=body.bandwidth_limit_kb,
        extra_rsync_args=body.extra_rsync_args,
        snapshot_policy_hint=hint,
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
        scheduler_service.update_file_replication_schedule(job.id, job.schedule)
    return _job_out(job)


@router.get("/{job_id}", response_model=FileReplicationJobOut)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return _job_out(job)


@router.put("/{job_id}", response_model=FileReplicationJobOut)
def update_job(
    job_id: int,
    body: FileReplicationJobUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")

    data = body.model_dump(exclude_unset=True)
    if "snapshot_policy_hint" in data and data["snapshot_policy_hint"] is not None:
        hint = data["snapshot_policy_hint"]
        data["snapshot_policy_hint"] = hint.model_dump() if hasattr(hint, "model_dump") else hint
    if "source_paths" in data and data["source_paths"] is not None:
        data["source_paths"] = [sanitize_path(p) for p in data["source_paths"]]
    if "dest_staging_path" in data and data["dest_staging_path"] is not None:
        data["dest_staging_path"] = sanitize_path(data["dest_staging_path"])

    for key, value in data.items():
        setattr(job, key, value)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)

    if job.schedule and job.is_active:
        scheduler_service.update_file_replication_schedule(job.id, job.schedule)
    else:
        scheduler_service.remove_file_replication_schedule(job.id)
    return _job_out(job)


@router.delete("/{job_id}")
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    scheduler_service.remove_file_replication_schedule(job.id)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.post("/{job_id}/run")
async def run_job(
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    if is_job_running(job_id):
        raise HTTPException(status_code=409, detail="Job già in esecuzione")
    asyncio.create_task(execute_file_replication_job(job_id))
    return {"ok": True, "message": "Esecuzione avviata"}


@router.post("/{job_id}/toggle", response_model=FileReplicationJobOut)
def toggle_job(
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    job.is_active = not job.is_active
    db.commit()
    db.refresh(job)
    if job.is_active and job.schedule:
        scheduler_service.update_file_replication_schedule(job.id, job.schedule)
    else:
        scheduler_service.remove_file_replication_schedule(job.id)
    return _job_out(job)


@router.get("/{job_id}/logs")
def job_logs(
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    logs = (
        db.query(JobLog)
        .filter(JobLog.job_type == "file_replication", JobLog.job_id == job_id)
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
            "created_at": log.started_at,
        }
        for log in logs
    ]


@router.get("/{job_id}/progress")
def job_progress(
    job_id: int,
    _user: User = Depends(get_current_user),
):
    prog = get_job_progress(job_id)
    if not prog:
        return {"status": "idle"}
    return prog
