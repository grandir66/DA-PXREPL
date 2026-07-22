"""Notifiche risultato job Snapshot VM (riusa notification_service globale)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def notify_vm_snapshot_result(
    job,
    *,
    status: str,
    duration: int,
    results: list[dict] | None = None,
    error: str | None = None,
    is_scheduled: bool = False,
) -> None:
    """Invia notifica secondo job.notify_mode (never|failure|always|daily).

    `partial` è trattato come esito da segnalare anche in modalità failure.
    """
    mode = (job.notify_mode or "never").lower()
    if mode == "never":
        return
    if mode == "failure" and status == "success":
        return
    try:
        from services.notification_service import notification_service

        results = results or []
        ok = sum(1 for r in results if r.get("created"))
        failed = sum(1 for r in results if r.get("error"))
        pruned = sum(len(r.get("pruned") or []) for r in results)
        details = (
            f"Snapshot creati: {ok}/{len(results)} VM — potati {pruned} — label {job.label}"
        )
        if failed:
            failed_vms = ", ".join(
                f"{r.get('vm_name') or r.get('vmid')}" for r in results if r.get("error")
            )
            details += f" — falliti: {failed_vms}"

        await notification_service.send_job_notification(
            job_name=job.name,
            status="failed" if status == "failed" else ("warning" if status == "partial" else "success"),
            source=f"{len(results)} VM",
            destination=f"snapshot Proxmox (label {job.label}, keep {job.keep})",
            duration=duration,
            error=error,
            details=details,
            job_id=job.id,
            is_scheduled=is_scheduled,
            notify_mode=mode,
            job_type="vm_snapshot",
            notify_subject=job.notify_subject,
        )
    except Exception as exc:  # noqa: BLE001 — la notifica non deve rompere il run
        logger.warning("Notifica vm_snapshot %s non inviata: %s", job.id, exc)
