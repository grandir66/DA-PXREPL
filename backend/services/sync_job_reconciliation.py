"""Riconciliazione stato job sync dopo restart o run lunghe."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from services.scheduler import scheduler_service
from services.syncoid_service import syncoid_service
from services.sync_job_execution import (
    _finalize_sync_job,
    _monitor_sync_job_completion,
    _try_register_vm_after_sync,
    repair_terminal_job_log,
)
from services.vm_group_sync_service import vm_group_sync_complete as _vm_group_sync_complete

logger = logging.getLogger(__name__)

_DIRECT_SYNC_MAX_AGE = {
    "pve_native": timedelta(hours=8),
    "btrfs_send": timedelta(hours=3),
}


async def _is_direct_sync_process_active(job, source, dest) -> bool:
    """Verifica se vzdump/btrfs send è ancora in esecuzione sui nodi."""
    from database import SyncMethod
    from services.ssh_service import ssh_service

    sync_method = job.sync_method or SyncMethod.SYNCOID.value
    if sync_method == SyncMethod.PVE_NATIVE.value:
        pattern = r"vzdump|qmrestore|pct restore|scp.*\.(vma|tar)"
        hosts = [source, dest]
    elif sync_method == SyncMethod.BTRFS_SEND.value:
        pattern = r"btrfs send|btrfs receive"
        hosts = [source, dest]
    else:
        return False

    for node in hosts:
        if not node:
            continue
        try:
            result = await ssh_service.execute(
                hostname=node.hostname,
                command=f"pgrep -af '{pattern}' 2>/dev/null || true",
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path,
                timeout=15,
            )
            out = (result.stdout or "").strip()
            if out and "pgrep" not in out.lower():
                return True
        except Exception:
            continue
    return False


async def _reconcile_direct_sync_job(job, log, db) -> None:
    """Allinea job PVE native / BTRFS non monitorati da syncoid."""
    from database import Node, SyncMethod

    sync_method = job.sync_method or SyncMethod.SYNCOID.value
    job_key = f"sync_{job.id}"
    status = (log.status or "").lower()

    if log.completed_at and status in ("started", "running"):
        if repair_terminal_job_log(log, job):
            if (job.last_status or "").lower() == "running":
                job.last_status = log.status
                if hasattr(job, "current_status"):
                    try:
                        job.current_status = "idle"
                    except Exception:
                        pass
            db.commit()
        return

    if status in ("success", "failed"):
        if (job.last_status or "").lower() == "running":
            job.last_status = status
            if hasattr(job, "current_status"):
                try:
                    job.current_status = "idle"
                except Exception:
                    pass
            job.last_run = log.completed_at or datetime.utcnow()
            db.commit()
        scheduler_service.mark_done(job_key)
        return

    if status not in ("started", "running") or log.completed_at:
        return

    started_at = log.started_at or datetime.utcnow()
    max_age = _DIRECT_SYNC_MAX_AGE.get(sync_method, timedelta(hours=6))
    if datetime.utcnow() - started_at < max_age:
        return

    source = db.query(Node).filter(Node.id == job.source_node_id).first()
    dest = db.query(Node).filter(Node.id == job.dest_node_id).first()
    if await _is_direct_sync_process_active(job, source, dest):
        return

    log.status = "failed"
    log.completed_at = datetime.utcnow()
    log.message = (log.message or "") + " | Reconcile: job bloccato, segnato failed"
    log.error = (log.error or "") + "Reconcile timeout"
    job.last_status = "failed"
    if hasattr(job, "current_status"):
        try:
            job.current_status = "idle"
        except Exception:
            pass
    job.error_count = (job.error_count or 0) + 1
    job.consecutive_failures = (job.consecutive_failures or 0) + 1
    job.last_run = datetime.utcnow()
    db.commit()
    scheduler_service.mark_done(job_key)
    logger.info(f"Reconcile: job diretto {job.id} ({sync_method}) segnato failed")


def reconcile_stale_job_logs(db) -> int:
    """Corregge job_log con completed_at ma status ancora started/running."""
    from database import JobLog, SyncJob

    fixed = 0
    logs = (
        db.query(JobLog)
        .filter(
            JobLog.completed_at.isnot(None),
            JobLog.status.in_(("started", "running")),
        )
        .all()
    )
    for log in logs:
        job = None
        if log.job_id is not None:
            job = db.query(SyncJob).filter(SyncJob.id == log.job_id).first()
        if repair_terminal_job_log(log, job):
            fixed += 1
    if fixed:
        db.commit()
        logger.info(f"Reconcile: corretti {fixed} job_log con status incoerente")
    return fixed


async def _reconcile_running_sync_jobs_once() -> None:
    """Periodicamente: chiude job completati o riavvia monitor caduti."""
    from database import SessionLocal, SyncJob, Node, JobLog, SyncMethod

    db = SessionLocal()
    try:
        reconcile_stale_job_logs(db)

        jobs = db.query(SyncJob).filter(SyncJob.last_status == "running").all()
        for job in jobs:
            sync_method = job.sync_method or SyncMethod.SYNCOID.value
            log = (
                db.query(JobLog)
                .filter(JobLog.job_id == job.id)
                .order_by(JobLog.started_at.desc())
                .first()
            )
            if not log:
                continue

            if sync_method in (SyncMethod.BTRFS_SEND.value, SyncMethod.PVE_NATIVE.value):
                await _reconcile_direct_sync_job(job, log, db)
                continue

            source = db.query(Node).filter(Node.id == job.source_node_id).first()
            dest = db.query(Node).filter(Node.id == job.dest_node_id).first()
            if not source or not dest:
                continue
            try:
                active = await syncoid_service.is_replication_active(
                    executor_host=source.hostname,
                    executor_port=source.ssh_port,
                    executor_user=source.ssh_user,
                    executor_key=source.ssh_key_path,
                    source_dataset=job.source_dataset,
                    dest_host=dest.hostname,
                    dest_port=dest.ssh_port,
                    dest_user=dest.ssh_user,
                    dest_key=dest.ssh_key_path,
                    dest_dataset=job.dest_dataset,
                )
            except Exception:
                active = False

            job_key = f"sync_{job.id}"
            if not active:
                if not log.completed_at:
                    await _finalize_sync_job(
                        job.id, log.id, dest, job.dest_dataset, job_key
                    )
                elif (log.status or "").lower() in ("started", "running"):
                    if repair_terminal_job_log(log, job):
                        job.last_status = log.status
                        if hasattr(job, "current_status"):
                            try:
                                job.current_status = "idle"
                            except Exception:
                                pass
                        db.commit()
                continue

            if scheduler_service.is_running(job_key):
                continue

            scheduler_service.mark_running(job_key)
            asyncio.create_task(
                _monitor_sync_job_completion(
                    job_id=job.id,
                    job_key=job_key,
                    log_entry_id=log.id,
                    source_node=source,
                    dest_node=dest,
                    source_dataset=job.source_dataset,
                    dest_dataset=job.dest_dataset,
                )
            )
            logger.info(f"Reconcile: monitor riavviato per job {job.id}")
    except Exception as e:
        logger.warning(f"Reconcile running sync jobs fallito: {e}")
    finally:
        db.close()


async def reconcile_pending_vm_registrations() -> None:
    """Registra VM mancanti per job già in success (es. completati via monitor)."""
    from database import SessionLocal, SyncJob, Node, JobLog
    from services.ssh_service import ssh_service

    db = SessionLocal()
    try:
        jobs = db.query(SyncJob).filter(
            SyncJob.last_status == "success",
            SyncJob.register_vm == True,  # noqa: E712
            SyncJob.vm_id.isnot(None),
        ).all()
        for job in jobs:
            if not _vm_group_sync_complete(db, job):
                continue
            target_vmid = job.dest_vm_id or job.vm_id
            dest = db.query(Node).filter(Node.id == job.dest_node_id).first()
            if not dest:
                continue
            vm_type = job.vm_type or "qemu"
            conf = (
                f"/etc/pve/qemu-server/{target_vmid}.conf"
                if vm_type == "qemu"
                else f"/etc/pve/lxc/{target_vmid}.conf"
            )
            exists = await ssh_service.execute(
                hostname=dest.hostname,
                command=f"test -f {conf} && echo yes",
                port=dest.ssh_port,
                username=dest.ssh_user,
                key_path=dest.ssh_key_path,
                timeout=15,
            )
            if "yes" in (exists.stdout or ""):
                continue
            log = (
                db.query(JobLog)
                .filter(JobLog.job_id == job.id)
                .order_by(JobLog.started_at.desc())
                .first()
            )
            if not log:
                continue
            if "registrata" in (log.message or ""):
                continue
            await _try_register_vm_after_sync(job.id, log.id)
    except Exception as e:
        logger.warning(f"Reconcile registrazioni VM pendenti fallito: {e}")
    finally:
        db.close()


async def reconcile_sync_jobs_after_restart() -> None:
    """Allinea DB e riavvia monitor per replica ancora attiva dopo restart backend."""
    from database import SessionLocal, SyncJob, Node, SyncMethod

    db = SessionLocal()
    try:
        reconcile_stale_job_logs(db)

        jobs = db.query(SyncJob).filter(SyncJob.last_status == "failed").all()
        for job in jobs:
            sync_method = job.sync_method or SyncMethod.SYNCOID.value
            if sync_method in (SyncMethod.BTRFS_SEND.value, SyncMethod.PVE_NATIVE.value):
                continue
            source = db.query(Node).filter(Node.id == job.source_node_id).first()
            dest = db.query(Node).filter(Node.id == job.dest_node_id).first()
            if not source or not dest:
                continue
            try:
                active = await syncoid_service.is_replication_active(
                    executor_host=source.hostname,
                    executor_port=source.ssh_port,
                    executor_user=source.ssh_user,
                    executor_key=source.ssh_key_path,
                    source_dataset=job.source_dataset,
                    dest_host=dest.hostname,
                    dest_port=dest.ssh_port,
                    dest_user=dest.ssh_user,
                    dest_key=dest.ssh_key_path,
                    dest_dataset=job.dest_dataset,
                )
            except Exception:
                active = False
            if active:
                job.last_status = "running"
                if hasattr(job, "current_status"):
                    try:
                        job.current_status = "running"
                    except Exception:
                        pass
                logger.info(
                    f"Reconcile startup: job {job.id} failed in DB ma ancora attivo → running"
                )
        db.commit()
    except Exception as e:
        logger.warning(f"Reconcile sync jobs startup fallito: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()

    await _reconcile_running_sync_jobs_once()
    await reconcile_pending_vm_registrations()
