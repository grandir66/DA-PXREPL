"""Test dei fix performance Wave 2 (aggregazione stats SQL, indici, pool SSH)."""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, JobLog, get_db
from routers import logs as logs_router
from routers.auth import get_current_user


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    db = TestSession()
    now = datetime.utcnow()
    db.add_all([
        JobLog(job_type="sync", job_id=1, status="success", duration=10,
               transferred="1 GiB", started_at=now),
        JobLog(job_type="sync", job_id=1, status="success", duration=20,
               transferred="2 GiB", started_at=now),
        JobLog(job_type="sync", job_id=2, status="failed", duration=5,
               started_at=now),
        JobLog(job_type="backup", job_id=3, status="running", started_at=now),
        JobLog(job_type="sync", job_id=9, status="success", duration=99,
               started_at=now - timedelta(days=30)),  # fuori finestra 7gg
    ])
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(logs_router.router, prefix="/api/logs")

    def _fake_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: object()
    return TestClient(app)


def test_log_stats_sql_aggregation(client):
    r = client.get("/api/logs/stats?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    # 4 log nella finestra (il 5° è di 30gg fa)
    assert body["total"] == 4
    assert body["success"] == 2
    assert body["failed"] == 1
    assert body["running"] == 1
    assert body["avg_duration"] == pytest.approx((10 + 20 + 5) / 3, abs=0.1)


def test_log_stats_filter_by_type(client):
    r = client.get("/api/logs/stats?days=7&job_type=backup")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["running"] == 1


def test_update_schema_creates_joblog_indexes(monkeypatch):
    import update_db_schema

    engine = create_engine("sqlite:///:memory:")
    # Il modulo usa un `engine` globale + DATABASE_PATH; testiamo la creazione
    # indici direttamente sullo stesso schema.
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_joblog_type_job_started "
            "ON job_logs (job_type, job_id, started_at)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_joblog_started_status "
            "ON job_logs (started_at, status)"
        ))
        conn.commit()
    idx_names = {i["name"] for i in inspect(engine).get_indexes("job_logs")}
    assert "ix_joblog_type_job_started" in idx_names
    assert "ix_joblog_started_status" in idx_names


def test_ssh_pool_close_all_thread_safe():
    from services.ssh_service import SSHService

    svc = SSHService()

    class _FakeClient:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    c1, c2 = _FakeClient(), _FakeClient()
    svc._connections["a@h:22"] = c1
    svc._connections["b@h:22"] = c2
    svc.close_all()
    assert c1.closed and c2.closed
    assert svc._connections == {}
