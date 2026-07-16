"""Test calcolo prossima run cron (no catch-up multi-giorno al restart)."""

from datetime import datetime

from services.scheduler import compute_initial_next_run


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
