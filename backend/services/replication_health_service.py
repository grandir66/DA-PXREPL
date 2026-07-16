"""Valutazione salute job di replica schedulati (run mancate)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from croniter import croniter


def check_job_overdue(
    schedule: Optional[str],
    last_run: Optional[datetime],
    *,
    now: Optional[datetime] = None,
    is_active: bool = True,
    last_status: Optional[str] = None,
) -> Dict[str, Any]:
    """True se l'ultimo slot cron atteso non ha prodotto una run completata."""
    now = now or datetime.utcnow()
    result: Dict[str, Any] = {
        "overdue": False,
        "expected_slot": None,
        "hours_since_last_run": None,
        "reason": None,
    }

    if not is_active or not schedule or not str(schedule).strip():
        return result

    status = (last_status or "").lower()
    if status in ("running", "started", "backing_up", "restoring"):
        return result

    try:
        prev_slot = croniter(str(schedule).strip(), now).get_prev(datetime)
    except (ValueError, KeyError):
        return result

    result["expected_slot"] = prev_slot.isoformat()

    if last_run:
        result["hours_since_last_run"] = round(
            (now - last_run).total_seconds() / 3600, 1
        )
        if last_run < prev_slot:
            result["overdue"] = True
            result["reason"] = "missed_scheduled_run"
    else:
        result["overdue"] = True
        result["reason"] = "never_ran"

    return result


def build_replication_health_report(
    sync_jobs: List[Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Report aggregato per dashboard."""
    now = now or datetime.utcnow()
    jobs_out: List[Dict[str, Any]] = []
    scheduled = 0
    overdue_count = 0

    for job in sync_jobs:
        schedule = getattr(job, "schedule", None)
        if not schedule or not str(schedule).strip():
            continue

        scheduled += 1
        overdue_info = check_job_overdue(
            schedule,
            getattr(job, "last_run", None),
            now=now,
            is_active=getattr(job, "is_active", True),
            last_status=getattr(job, "last_status", None),
        )

        entry = {
            "id": job.id,
            "name": job.name,
            "type": "sync",
            "sync_method": getattr(job, "sync_method", None),
            "vm_id": getattr(job, "vm_id", None),
            "vm_name": getattr(job, "vm_name", None),
            "vm_group_id": getattr(job, "vm_group_id", None),
            "schedule": schedule,
            "last_run": job.last_run.isoformat() if getattr(job, "last_run", None) else None,
            "last_status": getattr(job, "last_status", None),
            **overdue_info,
        }
        jobs_out.append(entry)
        if overdue_info["overdue"]:
            overdue_count += 1

    jobs_out.sort(
        key=lambda j: (not j["overdue"], -(j["hours_since_last_run"] or 0)),
    )

    return {
        "overdue_count": overdue_count,
        "healthy_count": scheduled - overdue_count,
        "total_scheduled": scheduled,
        "checked_at": now.isoformat(),
        "jobs": jobs_out,
    }
