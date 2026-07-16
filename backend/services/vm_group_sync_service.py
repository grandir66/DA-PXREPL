"""Orchestrazione replica sequenziale per gruppi VM multi-disco."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from database import SyncJob
from services.scheduler import scheduler_service

logger = logging.getLogger(__name__)


def vm_group_key(vm_group_id: str) -> str:
    return f"vmgroup_{vm_group_id}"


def vm_group_sync_complete(db, job: SyncJob) -> bool:
    """True se tutti i job disco dello stesso gruppo VM sono in success."""
    if not job.vm_group_id:
        return (job.last_status or "").lower() == "success"
    siblings = db.query(SyncJob).filter(
        SyncJob.vm_group_id == job.vm_group_id,
        SyncJob.dest_node_id == job.dest_node_id,
        SyncJob.is_active == True,  # noqa: E712
    ).all()
    if not siblings:
        return (job.last_status or "").lower() == "success"
    return all((s.last_status or "").lower() == "success" for s in siblings)


async def wait_sync_job_terminal(
    job_id: int,
    job_key: str,
    poll_sec: int = 15,
    max_iter: int = 1440,
) -> str:
    """Attende che un job sync termini (success/failed). max_iter ~6h @ 15s."""
    from database import SessionLocal

    for _ in range(max_iter):
        db = SessionLocal()
        try:
            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            st = (job.last_status or "").lower() if job else ""
        finally:
            db.close()
        if st in ("success", "failed"):
            return st
        if not scheduler_service.is_running(job_key) and st not in ("running", "started", ""):
            return st or "unknown"
        await asyncio.sleep(poll_sec)
    return "timeout"


async def execute_vm_group_sync_task(
    vm_group_id: str,
    triggered_by_user_id: int = None,
    force_rerun: bool = False,
) -> None:
    """Replica sequenziale di tutti i dischi di un gruppo VM."""
    from database import SessionLocal
    from services.sync_job_execution import execute_sync_job_task
    from services.sync_job_reconciliation import reconcile_pending_vm_registrations

    db = SessionLocal()
    try:
        jobs = (
            db.query(SyncJob)
            .filter(SyncJob.vm_group_id == vm_group_id, SyncJob.is_active == True)  # noqa: E712
            .order_by(SyncJob.id)
            .all()
        )
        job_ids = [j.id for j in jobs]
    finally:
        db.close()

    logger.info(f"VM group {vm_group_id}: avvio replica sequenziale ({len(job_ids)} dischi)")

    for job_id in job_ids:
        db = SessionLocal()
        try:
            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if not job:
                continue
            status = (job.last_status or "").lower()
        finally:
            db.close()

        if not force_rerun:
            if status == "success":
                continue
            if status == "failed":
                logger.warning(f"VM group {vm_group_id}: interrotto — job {job_id} fallito")
                break
        elif status in ("running", "started"):
            key = f"sync_{job_id}"
            final = await wait_sync_job_terminal(job_id, key)
            if final == "failed":
                logger.warning(f"VM group {vm_group_id}: job {job_id} fallito dopo attesa")
                break
            if final != "success":
                logger.warning(
                    f"VM group {vm_group_id}: job {job_id} non completato ({final}), skip"
                )
                continue

        job_key = f"sync_{job_id}"
        if scheduler_service.is_running(job_key):
            final = await wait_sync_job_terminal(job_id, job_key)
            if final == "success":
                continue
            if final == "failed":
                break
            continue

        if not scheduler_service.mark_running(job_key):
            final = await wait_sync_job_terminal(job_id, job_key)
            if final == "failed":
                break
            continue

        keep_lock = False
        try:
            keep_lock = await execute_sync_job_task(job_id, triggered_by_user_id)
        except Exception as e:
            logger.error(f"VM group {vm_group_id} job {job_id}: {e}", exc_info=True)
            scheduler_service.mark_done(job_key)
            break

        if keep_lock:
            final = await wait_sync_job_terminal(job_id, job_key)
            if final == "failed":
                break
        else:
            scheduler_service.mark_done(job_key)
            db = SessionLocal()
            try:
                job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
                if (job.last_status or "").lower() == "failed":
                    break
            finally:
                db.close()

    await reconcile_pending_vm_registrations()


async def run_vm_group_background(
    vm_group_id: str,
    group_key: str,
    triggered_by_user_id: int = None,
    force_rerun: bool = False,
) -> None:
    try:
        await execute_vm_group_sync_task(
            vm_group_id, triggered_by_user_id, force_rerun=force_rerun
        )
    finally:
        scheduler_service.mark_done(group_key)


async def continue_vm_group_chain(
    vm_group_id: str,
    triggered_by_user_id: int = None,
) -> None:
    """Avvia il disco successivo se un job del gruppo è appena terminato."""
    group_key = vm_group_key(vm_group_id)
    if scheduler_service.is_running(group_key):
        return

    from database import SessionLocal

    db = SessionLocal()
    try:
        jobs = (
            db.query(SyncJob)
            .filter(SyncJob.vm_group_id == vm_group_id, SyncJob.is_active == True)  # noqa: E712
            .order_by(SyncJob.id)
            .all()
        )
        if not jobs:
            return
        if any((j.last_status or "").lower() == "running" for j in jobs):
            return
        if all((j.last_status or "").lower() == "success" for j in jobs):
            from services.sync_job_reconciliation import reconcile_pending_vm_registrations

            await reconcile_pending_vm_registrations()
            return
        if any((j.last_status or "").lower() == "failed" for j in jobs):
            return
        pending = [j for j in jobs if (j.last_status or "").lower() != "success"]
        if not pending:
            return
    finally:
        db.close()

    if not scheduler_service.mark_running(group_key):
        return
    asyncio.create_task(
        run_vm_group_background(vm_group_id, group_key, triggered_by_user_id)
    )
