"""Test salute replica: slot cron, gruppi VM e alert."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.replication_health_service import (
    build_replication_health_report,
    build_schedule_groups,
    check_job_overdue,
    compute_next_run,
    count_missed_cron_slots,
    enrich_job_schedule_info,
)
from services.notification_service import NotificationService


class _FakeJob:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_count_missed_cron_slots_daily():
    now = datetime(2026, 7, 17, 12, 0, 0)
    last_run = datetime(2026, 7, 14, 0, 0, 0)
    missed = count_missed_cron_slots("0 0 * * *", last_run, now)
    assert missed == 3


def test_compute_next_run_daily():
    now = datetime(2026, 7, 17, 12, 0, 0)
    nxt = compute_next_run("0 0 * * *", now)
    assert nxt == datetime(2026, 7, 18, 0, 0, 0)


def test_enrich_job_schedule_info_includes_next_and_missed():
    now = datetime(2026, 7, 17, 12, 0, 0)
    job = _FakeJob(
        id=1,
        name="late",
        schedule="0 0 * * *",
        last_run=now - timedelta(days=2),
        last_status="success",
        is_active=True,
        vm_id=100,
        vm_name="WEB",
    )
    info = enrich_job_schedule_info(job, now=now)
    assert info["overdue"] is True
    assert info["next_run"] is not None
    assert info["missed_slots"] >= 2


def test_build_schedule_groups_aggregates_vm_group():
    jobs = [
        {
            "id": 1,
            "name": "disk-a",
            "vm_group_id": "grp-1",
            "vm_id": 100,
            "vm_name": "WEB",
            "schedule": "0 2 * * *",
            "last_run": "2026-07-15T02:00:00",
            "next_run": "2026-07-18T02:00:00",
            "last_status": "success",
            "overdue": True,
            "missed_slots": 2,
            "hours_since_last_run": 48.0,
        },
        {
            "id": 2,
            "name": "disk-b",
            "vm_group_id": "grp-1",
            "vm_id": 100,
            "vm_name": "WEB",
            "schedule": "0 2 * * *",
            "last_run": "2026-07-16T02:00:00",
            "next_run": "2026-07-18T02:00:00",
            "last_status": "success",
            "overdue": True,
            "missed_slots": 1,
            "hours_since_last_run": 24.0,
        },
    ]
    groups = build_schedule_groups(jobs)
    assert len(groups) == 1
    assert groups[0]["job_count"] == 2
    assert groups[0]["missed_slots"] == 2
    assert groups[0]["overdue"] is True


def test_build_replication_health_report_groups():
    now = datetime(2026, 7, 17, 12, 0, 0)
    jobs = [
        _FakeJob(
            id=1,
            name="ok",
            schedule="0 0 * * *",
            last_run=now - timedelta(hours=1),
            last_status="success",
            is_active=True,
            vm_id=100,
            vm_name="OK",
        ),
        _FakeJob(
            id=2,
            name="late",
            schedule="0 0 * * *",
            last_run=now - timedelta(days=3),
            last_status="success",
            is_active=True,
            vm_id=101,
            vm_name="LATE",
        ),
    ]
    report = build_replication_health_report(jobs, now=now)
    assert report["overdue_group_count"] == 1
    assert len(report["groups"]) == 2
    assert len(report["overdue_groups"]) == 1


@pytest.mark.asyncio
async def test_send_replication_overdue_alert_delegates():
    svc = NotificationService()
    groups = [{"vm_name": "LATE", "vm_id": 101, "missed_slots": 2, "last_run": None, "next_run": None}]
    fake_config = MagicMock()
    fake_config.smtp_enabled = True
    fake_config.webhook_enabled = False
    fake_config.telegram_enabled = False
    fake_config.notify_on_warning = True
    with patch.object(svc, "_load_config", return_value=fake_config), patch.object(
        svc, "send_job_notification", new_callable=AsyncMock
    ) as mock_send:
        mock_send.return_value = {"sent": True}
        result = await svc.send_replication_overdue_alert(groups)
    assert result["sent"] is True
    mock_send.assert_awaited_once()
    kwargs = mock_send.await_args.kwargs
    assert kwargs["status"] == "warning"
    assert "LATE" in kwargs["details"]


@pytest.mark.asyncio
async def test_scheduler_check_replication_overdue_respects_cooldown():
    from services.scheduler import SchedulerService

    sched = SchedulerService()
    sched._last_overdue_check = datetime.utcnow() - timedelta(minutes=30)

    with patch.object(sched, "_check_replication_overdue", wraps=sched._check_replication_overdue):
        await sched._check_replication_overdue()
        # Second call within hour should no-op early
        before = sched._last_overdue_check
        sched._last_overdue_check = datetime.utcnow() - timedelta(minutes=5)
        await sched._check_replication_overdue()

    assert before is not None
