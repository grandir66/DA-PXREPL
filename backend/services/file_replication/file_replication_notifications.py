"""Notifiche email per job replica file."""

from __future__ import annotations

import logging

from database import FileEndpoint, FileReplicationJob
from services.file_replication.file_replication_report import (
    build_file_replication_report,
    report_transferred_human,
)
from services.notification_service import notification_service

logger = logging.getLogger(__name__)


async def notify_file_replication_result(
    *,
    job: FileReplicationJob,
    source: FileEndpoint,
    dest: FileEndpoint,
    status: str,
    duration: int,
    progress: dict | None = None,
    total_bytes: int = 0,
    error: str | None = None,
    is_scheduled: bool = False,
) -> None:
    if job.notify_mode == "never":
        return
    if job.notify_mode == "failure" and status != "failed":
        return
    if status == "success" and job.notify_mode not in ("always", "daily"):
        return
    if status == "failed" and job.notify_mode not in ("always", "failure", "daily"):
        return

    paths_preview = ", ".join(job.source_paths or [])[:500]
    report = build_file_replication_report(
        job=job,
        source=source,
        dest=dest,
        duration_sec=duration,
        progress=progress,
        total_bytes=total_bytes,
    )

    try:
        await notification_service.send_job_notification(
            job_name=job.name,
            status=status,
            source=f"{source.name}: {paths_preview or '—'}",
            destination=f"{dest.name}: {job.dest_staging_path}",
            duration=duration,
            error=error,
            details=report[:4000],
            job_id=job.id,
            is_scheduled=is_scheduled,
            notify_mode=job.notify_mode or "daily",
            transferred=report_transferred_human(progress, total_bytes),
            job_type="file_replication",
            source_node_name=source.name,
            dest_node_name=dest.name,
            notify_subject=job.notify_subject,
        )
    except Exception as exc:
        logger.warning("Notifica file replication fallita per job %s: %s", job.id, exc)
