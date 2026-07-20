"""Test orchestratore nas_sync con engine finto e DB in memoria."""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
from database import Base, FileEndpoint, FileEndpointType, JobLog
from services.nas_sync import execution
from services.nas_sync.engine_direct_rsync import EngineCancelled, StepResult
from services.nas_sync.models import NasSyncJob


@pytest.fixture()
def db_session(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(execution, "SessionLocal", TestSession)
    db = TestSession()
    src = FileEndpoint(name="s", endpoint_type=FileEndpointType.SYNOLOGY, host="1", port=1,
                       protocol="api", username="u", password_enc="x", extra_config={})
    dst = FileEndpoint(name="d", endpoint_type=FileEndpointType.QNAP, host="2", port=1,
                       protocol="api", username="u", password_enc="x",
                       extra_config={"rsync_module": "DATI", "rsync_password_enc": "x"})
    db.add_all([src, dst])
    db.commit()
    job = NasSyncJob(name="j", source_endpoint_id=src.id, dest_endpoint_id=dst.id,
                     source_paths=["/Condivisa/docs"], dest_base_path="", sync_method="auto",
                     notify_mode="never")
    db.add(job)
    db.commit()
    yield db, TestSession, job.id
    db.close()


def test_success_run_updates_job_and_log(db_session):
    db, TestSession, job_id = db_session

    async def fake_engine(step_ctx):
        return StepResult(output_lines=["x"], exit_code=0)

    asyncio.run(execution.execute_nas_sync_job(job_id, _engine_runner=fake_engine))

    check = TestSession()
    job = check.query(NasSyncJob).get(job_id)
    assert job.last_run_status == "success"
    assert job.current_status == "idle"
    assert job.resolved_engine == "direct_rsync"
    log = check.query(JobLog).filter(JobLog.job_type == "nas_sync").first()
    assert log is not None and log.status == "success"
    check.close()


def test_engine_failure_marks_failed(db_session):
    db, TestSession, job_id = db_session

    async def fake_engine(step_ctx):
        raise RuntimeError("boom rete")

    asyncio.run(execution.execute_nas_sync_job(job_id, _engine_runner=fake_engine))
    check = TestSession()
    job = check.query(NasSyncJob).get(job_id)
    assert job.last_run_status == "failed"
    assert job.current_status == "failed"
    check.close()


def test_cancel_marks_paused_with_checkpoint(db_session):
    db, TestSession, job_id = db_session

    async def fake_engine(step_ctx):
        raise EngineCancelled("stop")

    asyncio.run(execution.execute_nas_sync_job(job_id, _engine_runner=fake_engine))
    check = TestSession()
    job = check.query(NasSyncJob).get(job_id)
    assert job.current_status == "paused"
    assert (job.run_state or {}).get("pause")
    check.close()


def test_double_run_guard(db_session):
    db, TestSession, job_id = db_session
    execution._running.add(job_id)
    try:
        asyncio.run(execution.execute_nas_sync_job(job_id))
        check = TestSession()
        job = check.query(NasSyncJob).get(job_id)
        assert job.last_run_status is None  # non ha girato
        check.close()
    finally:
        execution._running.discard(job_id)
