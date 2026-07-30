"""Valutazione cron in ora locale (condivisa tra scheduler e health-check).

Lo scheduler fa partire i job interpretando la stringa cron in ora LOCALE
(_SCHEDULER_TZ, default Europe/Rome), pur mantenendo storage e confronti in UTC
naive. Qualunque altro componente che valuta gli stessi cron (es. il check
"replica in ritardo") DEVE usare questi helper, altrimenti calcola gli slot in
UTC e va fuori fase di N ore (bug alert "in ritardo" falsi).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from croniter import croniter
from zoneinfo import ZoneInfo

_TZ_NAME = os.environ.get("DAPX_SCHEDULER_TZ", "Europe/Rome")
try:
    SCHEDULER_TZ = ZoneInfo(_TZ_NAME)
except Exception:  # zoneinfo mancante o nome errato → fallback UTC (comportamento legacy)
    SCHEDULER_TZ = ZoneInfo("UTC")


def next_run_after(schedule: str, after_utc: datetime) -> datetime:
    """Prossimo fire del cron DOPO `after_utc` (naive UTC), cron in ora locale. Ritorna naive UTC."""
    base_local = after_utc.replace(tzinfo=timezone.utc).astimezone(SCHEDULER_TZ)
    nxt = croniter(schedule, base_local).get_next(datetime)
    return nxt.astimezone(timezone.utc).replace(tzinfo=None)


def prev_run_before(schedule: str, before_utc: datetime) -> datetime:
    """Slot cron precedente (o corrente) rispetto a `before_utc`, cron in ora locale. Ritorna naive UTC."""
    base_local = before_utc.replace(tzinfo=timezone.utc).astimezone(SCHEDULER_TZ)
    prev = croniter(schedule, base_local).get_prev(datetime)
    return prev.astimezone(timezone.utc).replace(tzinfo=None)


def cron_iter_local(schedule: str, start_utc: datetime) -> croniter:
    """Iteratore croniter ancorato all'ora locale a partire da `start_utc` (naive UTC).
    Il chiamante deve riconvertire ogni `get_next(datetime)` in naive UTC."""
    base_local = start_utc.replace(tzinfo=timezone.utc).astimezone(SCHEDULER_TZ)
    return croniter(schedule, base_local)


def to_naive_utc(dt_local: datetime) -> datetime:
    """Converte un datetime aware (locale) in naive UTC."""
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)
