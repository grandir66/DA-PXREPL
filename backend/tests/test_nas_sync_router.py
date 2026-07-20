"""Test API router nas-sync (TestClient, auth override, DB in memoria)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, FileEndpoint, FileEndpointType, get_db
from routers import nas_sync_jobs
from routers.auth import get_current_user, require_operator
from services.nas_sync.models import NasSyncJob


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    db = TestSession()
    src = FileEndpoint(name="syno", endpoint_type=FileEndpointType.SYNOLOGY, host="1",
                       port=1, protocol="api", username="u", password_enc="x", extra_config={})
    dst = FileEndpoint(name="qnap", endpoint_type=FileEndpointType.QNAP, host="2",
                       port=1, protocol="api", username="u", password_enc="x",
                       extra_config={"rsync_module": "DATI", "rsync_password_enc": "x"})
    db.add_all([src, dst])
    db.commit()
    src_id, dst_id = src.id, dst.id
    db.close()

    app = FastAPI()
    app.include_router(nas_sync_jobs.router, prefix="/api/nas-sync")

    def _fake_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[require_operator] = lambda: object()
    return TestClient(app), src_id, dst_id


def test_create_and_list_job(client):
    c, src_id, dst_id = client
    payload = {
        "name": "replica-docs",
        "source_endpoint_id": src_id,
        "dest_endpoint_id": dst_id,
        "source_paths": ["/Condivisa/docs"],
        "dest_base_path": "/share/DATI",
    }
    r = c.post("/api/nas-sync", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sync_method"] == "auto"
    assert body["resolved_engine"] == "direct_rsync"  # calcolato alla create

    r = c.get("/api/nas-sync")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_create_rejects_missing_endpoint(client):
    c, src_id, _ = client
    r = c.post("/api/nas-sync", json={
        "name": "x", "source_endpoint_id": src_id, "dest_endpoint_id": 999,
        "source_paths": ["/A"], "dest_base_path": "/share/D",
    })
    assert r.status_code == 400


def test_capabilities_endpoint(client):
    c, src_id, _ = client
    r = c.get(f"/api/nas-sync/endpoints/{src_id}/capabilities")
    assert r.status_code == 200
    caps = r.json()
    assert caps["rsync_source"] is True
    assert caps["smb"] is True


def test_stats_summary(client):
    c, _, _ = client
    r = c.get("/api/nas-sync/stats/summary")
    assert r.status_code == 200
    assert r.json()["total"] == 0
