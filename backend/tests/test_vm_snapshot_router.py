"""Test API router vm-snapshots (TestClient, auth override, DB in memoria)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from routers import vm_snapshot_jobs
from routers.auth import get_current_user, require_operator
from services.vm_snapshot.models import VmSnapshotJob


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(vm_snapshot_jobs.router, prefix="/api/vm-snapshots")

    def _fake_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[require_operator] = lambda: object()

    schedule_calls = []
    monkeypatch.setattr(
        vm_snapshot_jobs.scheduler_service,
        "update_vm_snapshot_schedule",
        lambda job_id, schedule, last_run=None: schedule_calls.append(("update", job_id, schedule)),
    )
    monkeypatch.setattr(
        vm_snapshot_jobs.scheduler_service,
        "remove_vm_snapshot_schedule",
        lambda job_id: schedule_calls.append(("remove", job_id)),
    )
    return TestClient(app), TestSession, schedule_calls


PAYLOAD = {
    "name": "snap-prod",
    "label": "daily",
    "keep": 7,
    "targets": [{"node_id": 1, "vmid": 100, "vm_type": "qemu", "name": "web01"}],
    "selectors": {"tags": ["prod"], "node_ids": [], "exclude_vmids": []},
    "schedule": "0 3 * * *",
}


def test_create_and_list(client):
    c, _, schedule_calls = client
    r = c.post("/api/vm-snapshots", json=PAYLOAD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "daily"
    assert body["keep"] == 7
    assert body["label_conflicts"] == []
    assert ("update", body["id"], "0 3 * * *") in schedule_calls

    r = c.get("/api/vm-snapshots")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_create_invalid_label_422(client):
    c, _, _ = client
    r = c.post("/api/vm-snapshots", json={**PAYLOAD, "label": "Bad_Label"})
    assert r.status_code == 422


def test_create_keep_zero_422(client):
    c, _, _ = client
    r = c.post("/api/vm-snapshots", json={**PAYLOAD, "keep": 0})
    assert r.status_code == 422


def test_create_without_selection_400(client):
    c, _, _ = client
    r = c.post("/api/vm-snapshots", json={**PAYLOAD, "targets": [], "selectors": {}})
    assert r.status_code == 400


def test_label_conflict_reported(client):
    c, _, _ = client
    c.post("/api/vm-snapshots", json=PAYLOAD)
    r = c.post("/api/vm-snapshots", json={**PAYLOAD, "name": "snap-prod-2"})
    assert r.status_code == 200
    assert r.json()["label_conflicts"] == ["snap-prod"]


def test_delete_removes_schedule(client):
    c, _, schedule_calls = client
    job_id = c.post("/api/vm-snapshots", json=PAYLOAD).json()["id"]
    r = c.delete(f"/api/vm-snapshots/{job_id}")
    assert r.status_code == 200
    assert ("remove", job_id) in schedule_calls


def test_run_conflict_when_running(client, monkeypatch):
    c, _, _ = client
    job_id = c.post("/api/vm-snapshots", json=PAYLOAD).json()["id"]
    monkeypatch.setattr(vm_snapshot_jobs, "is_job_running", lambda _id: True)
    r = c.post(f"/api/vm-snapshots/{job_id}/run")
    assert r.status_code == 409


def test_stats_summary(client):
    c, _, _ = client
    r = c.get("/api/vm-snapshots/stats/summary")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "active": 0, "running": 0, "failed": 0}


def test_toggle(client):
    c, TestSession, _ = client
    job_id = c.post("/api/vm-snapshots", json=PAYLOAD).json()["id"]
    r = c.post(f"/api/vm-snapshots/{job_id}/toggle")
    assert r.status_code == 200
    assert r.json()["is_active"] is False
