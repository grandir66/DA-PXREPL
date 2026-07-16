"""Test orchestrazione gruppi VM multi-disco."""

from datetime import datetime, timedelta

from services.replication_health_service import build_replication_health_report
from services.vm_group_sync_service import vm_group_key, vm_group_sync_complete


class _FakeJob:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, siblings):
        self._siblings = siblings

    def query(self, model):
        return _FakeQuery(self._siblings)


def test_vm_group_key():
    assert vm_group_key("abc-123") == "vmgroup_abc-123"


def test_vm_group_sync_complete_all_success():
    job = _FakeJob(vm_group_id="g1", dest_node_id=1, last_status="success")
    siblings = [
        _FakeJob(last_status="success"),
        _FakeJob(last_status="success"),
    ]
    assert vm_group_sync_complete(_FakeDb(siblings), job) is True


def test_vm_group_sync_complete_one_pending():
    job = _FakeJob(vm_group_id="g1", dest_node_id=1, last_status="success")
    siblings = [
        _FakeJob(last_status="success"),
        _FakeJob(last_status="running"),
    ]
    assert vm_group_sync_complete(_FakeDb(siblings), job) is False


def test_vm_group_sync_complete_standalone():
    job = _FakeJob(vm_group_id=None, last_status="success")
    assert vm_group_sync_complete(_FakeDb([]), job) is True


def test_health_report_flags_running_jobs():
    now = datetime(2026, 7, 17, 12, 0, 0)
    jobs = [
        _FakeJob(
            id=1,
            name="running-job",
            schedule="0 0 * * *",
            last_run=now - timedelta(hours=1),
            last_status="running",
            is_active=True,
            vm_id=100,
            vm_name="WEB",
        ),
        _FakeJob(
            id=2,
            name="ok-job",
            schedule="0 0 * * *",
            last_run=now - timedelta(minutes=30),
            last_status="success",
            is_active=True,
            vm_id=101,
            vm_name="DB",
        ),
    ]
    report = build_replication_health_report(jobs, now=now)
    assert report["running_count"] == 1
    assert len(report["running_jobs"]) == 1
