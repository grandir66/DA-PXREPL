"""Test orchestratore vm_snapshot con primitive Proxmox simulate e DB in memoria."""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, JobLog, Node
from services.vm_snapshot import execution
from services.vm_snapshot.models import VmSnapshotJob


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(execution, "SessionLocal", TestSession)

    db = TestSession()
    node = Node(name="px1", hostname="10.0.0.1", ssh_port=22, ssh_user="root",
                ssh_key_path="/root/.ssh/id_rsa")
    db.add(node)
    db.commit()
    job = VmSnapshotJob(
        name="snap-test", label="daily", keep=2, notify_mode="never",
        targets=[], selectors={"tags": ["prod"]},
    )
    db.add(job)
    db.commit()
    node_id, job_id = node.id, job.id
    db.close()

    targets = [
        {"node_id": node_id, "node_name": "px1", "vmid": 100, "name": "web01",
         "vm_type": "qemu", "status": "running", "tags": ["prod"],
         "has_pvesr": False, "source": "selector"},
        {"node_id": node_id, "node_name": "px1", "vmid": 101, "name": "db01",
         "vm_type": "lxc", "status": "running", "tags": ["prod"],
         "has_pvesr": True, "source": "selector"},
    ]

    async def fake_resolve(db_arg, job_arg):
        return targets

    monkeypatch.setattr(execution, "resolve_targets", fake_resolve)

    async def fake_prune(node_arg, vmid, vm_type, label, keep):
        return ([f"auto{label}_20260701_030000"], [])

    monkeypatch.setattr(execution, "prune_vm", fake_prune)
    return TestSession, job_id, targets, monkeypatch


def _run(job_id):
    asyncio.run(execution.execute_vm_snapshot_job(job_id))


def test_success_run(env):
    TestSession, job_id, targets, monkeypatch = env
    created_calls = []

    async def fake_create(**kwargs):
        created_calls.append(kwargs)
        return True, "ok"

    monkeypatch.setattr(execution.proxmox_service, "create_snapshot", fake_create)
    _run(job_id)

    db = TestSession()
    job = db.query(VmSnapshotJob).filter_by(id=job_id).first()
    assert job.last_run_status == "success"
    assert job.current_status == "idle"
    assert job.run_state["summary"] == {"ok": 2, "failed": 0, "pruned_total": 2}
    results = job.run_state["results"]
    assert all(r["created"] for r in results)
    assert results[0]["snapname"] == results[1]["snapname"]  # stesso nome per tutto il run
    assert results[0]["snapname"].startswith("autodaily_")
    # vmstate mai per lxc; qui include_vmstate=False → sempre False
    assert all(call["vmstate"] is False for call in created_calls)
    # pvesr → warning presente su db01
    by_vmid = {r["vmid"]: r for r in results}
    assert by_vmid[101]["warning"] and "pvesr" in by_vmid[101]["warning"]
    log = db.query(JobLog).filter_by(job_type="vm_snapshot").order_by(JobLog.id.desc()).first()
    assert log.status == "success"
    assert "autodaily_" in log.message
    db.close()


def test_partial_run_one_vm_fails(env):
    TestSession, job_id, targets, monkeypatch = env

    async def fake_create(**kwargs):
        if kwargs["vmid"] == 101:
            return False, "snapshot feature is not available"
        return True, "ok"

    monkeypatch.setattr(execution.proxmox_service, "create_snapshot", fake_create)
    _run(job_id)

    db = TestSession()
    job = db.query(VmSnapshotJob).filter_by(id=job_id).first()
    assert job.last_run_status == "partial"
    by_vmid = {r["vmid"]: r for r in job.run_state["results"]}
    assert by_vmid[100]["created"] is True
    assert by_vmid[101]["error"] == "snapshot feature is not available"
    log = db.query(JobLog).filter_by(job_type="vm_snapshot").order_by(JobLog.id.desc()).first()
    assert log.status == "warning"
    assert "101" in (log.error or "") or "db01" in (log.error or "")
    db.close()


def test_all_fail_is_failed(env):
    TestSession, job_id, targets, monkeypatch = env

    async def fake_create(**kwargs):
        return False, "boom"

    monkeypatch.setattr(execution.proxmox_service, "create_snapshot", fake_create)
    _run(job_id)

    db = TestSession()
    job = db.query(VmSnapshotJob).filter_by(id=job_id).first()
    assert job.last_run_status == "failed"
    db.close()


def test_empty_resolution_is_failed(env):
    TestSession, job_id, targets, monkeypatch = env

    async def empty_resolve(db_arg, job_arg):
        return []

    monkeypatch.setattr(execution, "resolve_targets", empty_resolve)
    _run(job_id)

    db = TestSession()
    job = db.query(VmSnapshotJob).filter_by(id=job_id).first()
    assert job.last_run_status == "failed"
    log = db.query(JobLog).filter_by(job_type="vm_snapshot").order_by(JobLog.id.desc()).first()
    assert log.status == "failed"
    assert "vuota" in (log.error or "")
    db.close()


def test_reentrancy_guard(env):
    TestSession, job_id, targets, monkeypatch = env
    execution._RUNNING[job_id] = {"status": "running"}
    try:
        _run(job_id)
        db = TestSession()
        job = db.query(VmSnapshotJob).filter_by(id=job_id).first()
        assert job.last_run_status is None  # non ha girato
        db.close()
    finally:
        execution._RUNNING.pop(job_id, None)


def test_vmstate_only_for_qemu(env):
    TestSession, job_id, targets, monkeypatch = env
    db = TestSession()
    job = db.query(VmSnapshotJob).filter_by(id=job_id).first()
    job.include_vmstate = True
    db.commit()
    db.close()
    calls = {}

    async def fake_create(**kwargs):
        calls[kwargs["vmid"]] = kwargs["vmstate"]
        return True, "ok"

    monkeypatch.setattr(execution.proxmox_service, "create_snapshot", fake_create)
    _run(job_id)
    assert calls[100] is True   # qemu
    assert calls[101] is False  # lxc: mai vmstate


def test_build_results_report_lists_each_vm():
    from services.vm_snapshot.notifications import build_results_report

    class J:
        label = "daily"
        keep = 7

    results = [
        {"vm_name": "web01", "vmid": 100, "vm_type": "qemu", "node_name": "px1",
         "snapname": "autodaily_20260722_031500", "created": True,
         "pruned": ["autodaily_20260715_030000"], "warning": None, "error": None},
        {"vm_name": "db01", "vmid": 101, "vm_type": "lxc", "node_name": "px2",
         "snapname": "autodaily_20260722_031500", "created": False,
         "pruned": [], "warning": None, "error": "lock vzdump"},
    ]
    report = build_results_report(J(), results, 95)
    assert "autodaily_20260722_031500" in report
    assert "label «daily»" in report and "mantieni 7" in report
    assert "riuscite: 1" in report and "fallite: 1" in report
    assert "✓ web01 (100, VM) @ px1" in report
    assert "potati 1: autodaily_20260715_030000" in report
    assert "✗ db01 (101, CT) @ px2 — ERRORE: lock vzdump" in report
    assert "1m 35s" in report
