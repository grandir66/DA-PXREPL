"""Test inventario PBS: raggruppamento e salute replica."""

from datetime import datetime, timedelta

from services.pbs_service import summarize_inventory_entries, filter_inventory_by_vmid
from services.replication_health_service import check_job_overdue, build_replication_health_report


class _FakeJob:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_summarize_inventory_groups_by_vmid():
    entries = [
        {"vmid": 100, "vm_name": "DA-WEB", "vm_type": "qemu", "backup_time": 1000, "size": 100},
        {"vmid": 100, "vm_name": "DA-WEB", "vm_type": "qemu", "backup_time": 2000, "size": 200},
        {"vmid": 201, "vm_name": "DA-SMTP", "vm_type": "qemu", "backup_time": 1500, "size": 50},
    ]
    summaries = summarize_inventory_entries(entries)
    assert len(summaries) == 2
    web = next(s for s in summaries if s["vmid"] == 100)
    assert web["backup_count"] == 2
    assert web["latest_backup_time"] == 2000
    assert web["latest_size"] == 200


def test_filter_inventory_by_vmid():
    entries = [
        {"vmid": 100, "backup_time": 1},
        {"vmid": 201, "backup_time": 2},
    ]
    filtered = filter_inventory_by_vmid(entries, 100)
    assert len(filtered) == 1
    assert filtered[0]["vmid"] == 100


def test_check_job_overdue_missed_run():
    now = datetime(2026, 7, 17, 12, 0, 0)
    last_run = datetime(2026, 7, 15, 0, 0, 0)
    result = check_job_overdue("0 0 * * *", last_run, now=now, is_active=True, last_status="success")
    assert result["overdue"] is True
    assert result["reason"] == "missed_scheduled_run"


def test_check_job_overdue_running_not_flagged():
    now = datetime(2026, 7, 17, 12, 0, 0)
    last_run = datetime(2026, 7, 15, 0, 0, 0)
    result = check_job_overdue("0 0 * * *", last_run, now=now, last_status="running")
    assert result["overdue"] is False


def test_check_job_overdue_never_ran():
    now = datetime(2026, 7, 17, 12, 0, 0)
    result = check_job_overdue("0 0 * * *", None, now=now, is_active=True)
    assert result["overdue"] is True
    assert result["reason"] == "never_ran"


def test_build_replication_health_report():
    now = datetime(2026, 7, 17, 12, 0, 0)
    jobs = [
        _FakeJob(
            id=1, name="ok-job", schedule="0 0 * * *",
            last_run=now - timedelta(hours=1), last_status="success",
            is_active=True, vm_id=100, vm_name="OK", sync_method="syncoid",
        ),
        _FakeJob(
            id=2, name="late-job", schedule="0 0 * * *",
            last_run=now - timedelta(days=3), last_status="success",
            is_active=True, vm_id=101, vm_name="LATE", sync_method="syncoid",
        ),
        _FakeJob(
            id=3, name="manual", schedule=None,
            last_run=None, last_status=None, is_active=True,
        ),
    ]
    report = build_replication_health_report(jobs, now=now)
    assert report["total_scheduled"] == 2
    assert report["overdue_count"] == 1
    assert report["healthy_count"] == 1
    overdue = [j for j in report["jobs"] if j["overdue"]]
    assert overdue[0]["name"] == "late-job"
