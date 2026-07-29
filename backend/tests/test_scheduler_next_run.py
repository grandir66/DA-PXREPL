"""Test calcolo prossima run cron (no catch-up multi-giorno al restart) + fuso locale."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import services.scheduler as scheduler
from services.scheduler import compute_initial_next_run


@pytest.fixture(autouse=True)
def _utc_scheduler_tz(monkeypatch):
    """La logica di catch-up è indipendente dal fuso: fissiamo UTC così che
    l'input/atteso naive coincida (nessun offset)."""
    monkeypatch.setattr(scheduler, "_SCHEDULER_TZ", ZoneInfo("UTC"))


def test_daily_no_stale_catchup_when_last_run_is_old():
    """Giovedì, last_run 16 giorni fa: prossima run = prossimo slot futuro, non backlog."""
    now = datetime(2026, 7, 16, 10, 0, 0)  # giovedì
    last = datetime(2026, 6, 30, 15, 0, 0)
    nxt = compute_initial_next_run("0 2 * * *", last, now)
    assert nxt == datetime(2026, 7, 17, 2, 0, 0)


def test_daily_fires_within_grace_window_after_slot_start():
    """Subito dopo lo slot 02:00, se non ancora eseguito → due now."""
    now = datetime(2026, 7, 16, 2, 1, 30)
    last = datetime(2026, 7, 15, 2, 5, 0)
    nxt = compute_initial_next_run("0 2 * * *", last, now)
    assert nxt == datetime(2026, 7, 16, 2, 0, 0)


def test_weekly_no_fire_on_wrong_weekday_after_restart():
    """Lunedì-only: giovedì restart non deve riprendere slot lunedi scorso."""
    now = datetime(2026, 7, 16, 10, 0, 0)  # giovedì
    last = datetime(2026, 6, 30, 3, 0, 0)
    nxt = compute_initial_next_run("0 2 * * 1", last, now)
    assert nxt == datetime(2026, 7, 20, 2, 0, 0)  # prossimo lunedì


def test_invalid_cron_is_parked_not_raised():
    """Cron non valido → non solleva (niente spam ogni tick): rimanda lontano."""
    now = datetime(2026, 7, 16, 10, 0, 0)
    nxt = compute_initial_next_run("non-un-cron", None, now)
    assert nxt > datetime(2027, 1, 1)


def test_cron_evaluated_in_local_timezone(monkeypatch):
    """Con TZ Europe/Rome (estate, UTC+2), '0 2' locale = 00:00 UTC nel DB (naive UTC)."""
    monkeypatch.setattr(scheduler, "_SCHEDULER_TZ", ZoneInfo("Europe/Rome"))
    now = datetime(2026, 7, 16, 10, 0, 0)  # naive UTC
    nxt = compute_initial_next_run("0 2 * * *", None, now)
    # 02:00 Europe/Rome del 17/07 = 00:00 UTC del 17/07
    assert nxt == datetime(2026, 7, 17, 0, 0, 0)
