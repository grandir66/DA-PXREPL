"""Notifiche email risultato job Repliche dati (riusa notification_service globale)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def notify_nas_sync_result(
    job,
    source,
    dest,
    *,
    status: str,
    duration: int,
    progress: dict | None = None,
    error: str | None = None,
    is_scheduled: bool = False,
) -> None:
    """Invia notifica secondo job.notify_mode (never|failure|always|daily)."""
    mode = (job.notify_mode or "never").lower()
    if mode == "never":
        return
    if mode == "failure" and status != "failed":
        return
    try:
        from services.notification_service import notification_service

        view = progress or {}
        report_lines = [view.get("display_summary") or ""]
        report_lines.extend(view.get("detail_lines") or [])
        if view.get("hint"):
            report_lines.append(f"Nota: {view['hint']}")
        report = "\n".join(line for line in report_lines if line)[:4000] or None

        await notification_service.send_job_notification(
            job_name=job.name,
            status=status,
            source=source.name,
            destination=dest.name,
            duration=duration,
            error=error,
            details=report,
            job_id=job.id,
            is_scheduled=is_scheduled,
            notify_mode=mode,
            transferred=(progress or {}).get("transferred_human"),
            job_type="nas_sync",
            source_node_name=source.name,
            dest_node_name=dest.name,
            notify_subject=job.notify_subject,
        )
    except Exception as exc:  # noqa: BLE001 — la notifica non deve rompere il run
        logger.warning("Notifica nas_sync %s non inviata: %s", job.id, exc)
