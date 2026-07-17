"""Test lifecycle job_log e reconcile."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_repair_terminal_job_log_from_job_status():
    from services.sync_job_execution import repair_terminal_job_log

    log = MagicMock()
    log.status = "started"
    log.completed_at = datetime.utcnow()
    log.error = None
    log.message = "done"

    job = MagicMock()
    job.last_status = "success"

    assert repair_terminal_job_log(log, job) is True
    assert log.status == "success"
    assert "status corretto" in log.message


def test_repair_terminal_job_log_infers_failed_from_error():
    from services.sync_job_execution import repair_terminal_job_log

    log = MagicMock()
    log.status = "running"
    log.completed_at = datetime.utcnow()
    log.error = "timeout"
    log.message = ""

    job = MagicMock()
    job.last_status = "running"

    assert repair_terminal_job_log(log, job) is True
    assert log.status == "failed"


def test_repair_terminal_job_log_noop_when_open():
    from services.sync_job_execution import repair_terminal_job_log

    log = MagicMock()
    log.status = "started"
    log.completed_at = None

    assert repair_terminal_job_log(log, MagicMock()) is False


def test_reconcile_stale_job_logs():
    from database import JobLog, SyncJob
    from services.sync_job_reconciliation import reconcile_stale_job_logs

    log = MagicMock()
    log.job_id = 1
    log.status = "started"
    log.completed_at = datetime.utcnow()
    log.error = None
    log.message = ""

    job = MagicMock()
    job.last_status = "success"

    db = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is JobLog:
            q.filter.return_value.all.return_value = [log]
        elif model is SyncJob:
            q.filter.return_value.first.return_value = job
        return q

    db.query.side_effect = query_side_effect

    fixed = reconcile_stale_job_logs(db)
    assert fixed == 1
    assert log.status == "success"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_monitor_timeout_marks_failed_when_still_active():
    from services.sync_job_execution import _apply_sync_monitor_timeout

    log = MagicMock()
    log.completed_at = None
    log.message = "running"
    log.error = None

    job = MagicMock()
    job.error_count = 0
    job.consecutive_failures = 0

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [job, log]

    with patch("database.SessionLocal", return_value=db):
        await _apply_sync_monitor_timeout(7, 99, still_active=True)

    assert log.status == "failed"
    assert log.completed_at is not None
    assert job.last_status == "failed"


@pytest.mark.asyncio
async def test_scheduler_reconcile_imports_resolve():
    from services.scheduler import SchedulerService

    sched = SchedulerService()
    await sched._reconcile_stuck_sync_jobs()
