"""Notifiche risultato job Snapshot VM (riusa notification_service globale).

Il report per-VM viaggia nel campo ``details`` dell'email (reso in <pre>):
una riga per VM con esito, nodo, snapshot potati e avvisi.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_DETAILS_CHARS = 6000


def build_results_report(job, results: list[dict], duration: int) -> str:
    """Report testuale multiriga: intestazione + una riga per VM."""
    results = results or []
    ok = sum(1 for r in results if r.get("created"))
    failed = sum(1 for r in results if r.get("error"))
    pruned_total = sum(len(r.get("pruned") or []) for r in results)
    snapname = next((r.get("snapname") for r in results if r.get("snapname")), "—")

    minutes, seconds = divmod(max(0, int(duration)), 60)
    dur = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"

    lines = [
        f"Snapshot: {snapname}",
        f"Politica: label «{job.label}» — mantieni {job.keep} copie",
        f"VM processate: {len(results)} · riuscite: {ok} · fallite: {failed} "
        f"· snapshot potati: {pruned_total} · durata: {dur}",
        "",
    ]
    for r in results:
        vm = f"{r.get('vm_name') or '?'} ({r.get('vmid')}, {'CT' if r.get('vm_type') == 'lxc' else 'VM'})"
        node = r.get("node_name") or "?"
        if r.get("error"):
            lines.append(f"✗ {vm} @ {node} — ERRORE: {r['error']}")
            continue
        parts = ["snapshot creato"]
        pruned = r.get("pruned") or []
        if pruned:
            parts.append(f"potati {len(pruned)}: {', '.join(pruned)}")
        else:
            parts.append("nessuno da potare")
        if r.get("warning"):
            parts.append(f"⚠ {r['warning']}")
        lines.append(f"✓ {vm} @ {node} — " + " · ".join(parts))

    report = "\n".join(lines)
    if len(report) > _MAX_DETAILS_CHARS:
        report = report[:_MAX_DETAILS_CHARS] + "\n… (report troncato)"
    return report


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

    ``partial`` è trattato come esito da segnalare anche in modalità failure.
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
        vm_name = None
        vm_id = None
        if len(results) == 1:
            vm_name = results[0].get("vm_name")
            vm_id = results[0].get("vmid")

        await notification_service.send_job_notification(
            job_name=job.name,
            status="failed" if status == "failed" else ("warning" if status == "partial" else "success"),
            source=f"{ok}/{len(results)} VM" if results else "0 VM",
            destination=f"Snapshot Proxmox — label {job.label}, keep {job.keep}",
            duration=duration,
            error=error,
            details=build_results_report(job, results, duration),
            job_id=job.id,
            is_scheduled=is_scheduled,
            notify_mode=mode,
            job_type="vm_snapshot",
            vm_name=vm_name,
            vm_id=vm_id,
            notify_subject=job.notify_subject,
        )
    except Exception as exc:  # noqa: BLE001 — la notifica non deve rompere il run
        logger.warning("Notifica vm_snapshot %s non inviata: %s", job.id, exc)
