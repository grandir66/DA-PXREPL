"""Test chiavi scheduler in-memory per SyncJob / VM group."""

from datetime import datetime

from services.scheduler import SchedulerService, compute_initial_next_run


def test_compute_initial_next_run_weekly_no_stale():
    now = datetime(2026, 7, 16, 10, 0, 0)
    nxt = compute_initial_next_run("0 2 * * 1", datetime(2026, 6, 30, 3, 0, 0), now)
    assert nxt == datetime(2026, 7, 20, 2, 0, 0)


def test_update_vm_group_schedule_uses_vmgroup_key():
    svc = SchedulerService()
    svc.update_vm_group_schedule("abc123", "0 2 * * *")
    assert "vmgroup_abc123" in svc._jobs
    assert "abc123" not in svc._jobs


def test_update_job_schedule_routes_to_vmgroup_when_set():
    svc = SchedulerService()
    svc.update_job_schedule(99, "0 3 * * *", vm_group_id="grp1")
    assert "vmgroup_grp1" in svc._jobs
    assert "sync_99" not in svc._jobs


def test_remove_vm_group_schedule():
    svc = SchedulerService()
    svc.update_vm_group_schedule("grp1", "0 2 * * *")
    svc.remove_vm_group_schedule("grp1")
    assert "vmgroup_grp1" not in svc._jobs
