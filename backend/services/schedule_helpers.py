"""Helper condivisi per allineamento schedule cron / schedule_config."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from services.schedule_translator import from_cron, to_cron


def resolve_schedule_pair(
    schedule: Optional[str],
    schedule_config: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Allinea cron e schedule_config prima di salvare un job."""
    if schedule_config is not None:
        cron = to_cron(schedule_config)
        return cron, schedule_config
    if schedule is not None:
        cron = schedule.strip() or None
        cfg = from_cron(cron) if cron else {"kind": "manual"}
        return cron, cfg
    return None, None
