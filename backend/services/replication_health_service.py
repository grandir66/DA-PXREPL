"""Valutazione salute job di replica schedulati (run mancate)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from croniter import croniter

# Ri-allerta notifiche se l'ultimo invio è più vecchio di N ore.
OVERDUE_ALERT_COOLDOWN_HOURS = 6


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


def compute_next_run(schedule: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    if not schedule or not str(schedule).strip():
        return None
    now = now or datetime.utcnow()
    try:
        return croniter(str(schedule).strip(), now).get_next(datetime)
    except (ValueError, KeyError):
        return None


def count_missed_cron_slots(
    schedule: Optional[str],
    last_run: Optional[datetime],
    now: Optional[datetime] = None,
    *,
    max_slots: int = 365,
) -> int:
    """Conta slot cron tra last_run e now non coperti da una run."""
    if not schedule or not str(schedule).strip():
        return 0
    now = now or datetime.utcnow()
    schedule = str(schedule).strip()

    if last_run is None:
        return 1

    try:
        itr = croniter(schedule, last_run)
    except (ValueError, KeyError):
        return 0

    missed = 0
    slot = itr.get_next(datetime)
    while slot <= now and missed < max_slots:
        missed += 1
        slot = itr.get_next(datetime)
    return missed


def enrich_job_schedule_info(
    job: Any,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Dettaglio pianificazione per un singolo SyncJob."""
    now = now or datetime.utcnow()
    schedule = getattr(job, "schedule", None)
    last_run = getattr(job, "last_run", None)
    overdue_info = check_job_overdue(
        schedule,
        last_run,
        now=now,
        is_active=getattr(job, "is_active", True),
        last_status=getattr(job, "last_status", None),
    )
    next_run = compute_next_run(schedule, now)
    missed = count_missed_cron_slots(schedule, last_run, now) if overdue_info["overdue"] else 0

    return {
        "id": job.id,
        "name": job.name,
        "type": "sync",
        "sync_method": getattr(job, "sync_method", None),
        "vm_id": getattr(job, "vm_id", None),
        "vm_name": getattr(job, "vm_name", None),
        "vm_group_id": getattr(job, "vm_group_id", None),
        "disk_name": getattr(job, "disk_name", None),
        "schedule": schedule,
        "last_run": last_run.isoformat() if last_run else None,
        "last_status": getattr(job, "last_status", None),
        "next_run": next_run.isoformat() if next_run else None,
        "missed_slots": missed,
        **overdue_info,
    }


def _group_key(job: Dict[str, Any]) -> str:
    gid = job.get("vm_group_id")
    if gid:
        return f"group:{gid}"
    vm_id = job.get("vm_id")
    if vm_id is not None:
        return f"vm:{vm_id}"
    return f"job:{job.get('id')}"


def build_schedule_groups(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggrega job per VM group (o singola VM) per la dashboard."""
    groups: Dict[str, Dict[str, Any]] = {}

    for job in jobs:
        if not job.get("schedule"):
            continue
        key = _group_key(job)
        group = groups.get(key)
        if not group:
            group = {
                "key": key,
                "vm_group_id": job.get("vm_group_id"),
                "vm_id": job.get("vm_id"),
                "vm_name": job.get("vm_name") or job.get("name"),
                "schedule": job.get("schedule"),
                "job_count": 0,
                "overdue": False,
                "missed_slots": 0,
                "hours_since_last_run": None,
                "last_run": None,
                "next_run": job.get("next_run"),
                "last_status": job.get("last_status"),
                "jobs": [],
            }
            groups[key] = group

        group["job_count"] += 1
        group["jobs"].append({"id": job["id"], "name": job["name"], "disk_name": job.get("disk_name")})

        if job.get("overdue"):
            group["overdue"] = True
            group["missed_slots"] = max(group["missed_slots"], job.get("missed_slots") or 0)
            hrs = job.get("hours_since_last_run")
            if hrs is not None and (group["hours_since_last_run"] is None or hrs > group["hours_since_last_run"]):
                group["hours_since_last_run"] = hrs

        lr = job.get("last_run")
        if lr and (group["last_run"] is None or lr > group["last_run"]):
            group["last_run"] = lr

        nr = job.get("next_run")
        if nr and (group["next_run"] is None or nr < group["next_run"]):
            group["next_run"] = nr

        if (job.get("last_status") or "").lower() == "failed":
            group["last_status"] = "failed"
        elif (job.get("last_status") or "").lower() in ("running", "started") and group["last_status"] != "failed":
            group["last_status"] = job.get("last_status")

    result = list(groups.values())
    result.sort(key=lambda g: (not g["overdue"], -(g["hours_since_last_run"] or 0)))
    return result


def build_replication_health_report(
    sync_jobs: List[Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Report aggregato per dashboard e alert."""
    now = now or datetime.utcnow()
    jobs_out: List[Dict[str, Any]] = []
    scheduled = 0
    overdue_count = 0

    for job in sync_jobs:
        schedule = getattr(job, "schedule", None)
        if not schedule or not str(schedule).strip():
            continue

        scheduled += 1
        entry = enrich_job_schedule_info(job, now=now)
        jobs_out.append(entry)
        if entry["overdue"]:
            overdue_count += 1

    jobs_out.sort(
        key=lambda j: (not j["overdue"], -(j["hours_since_last_run"] or 0)),
    )

    groups = build_schedule_groups(jobs_out)
    overdue_groups = [g for g in groups if g["overdue"]]

    return {
        "overdue_count": overdue_count,
        "overdue_group_count": len(overdue_groups),
        "healthy_count": scheduled - overdue_count,
        "total_scheduled": scheduled,
        "checked_at": now.isoformat(),
        "jobs": jobs_out,
        "groups": groups,
        "overdue_groups": overdue_groups,
    }
