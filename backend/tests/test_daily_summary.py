"""Test riepilogo giornaliero esteso a tutti i moduli."""

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, FileEndpoint, FileEndpointType, HostBackupJob, Node, SyncJob
from services import notification_service as ns_module
from services.nas_sync.models import NasSyncJob
from services.notification_service import notification_service
from services.vm_snapshot.models import VmSnapshotJob


class _StubConfig:
    smtp_enabled = True
    webhook_enabled = False
    telegram_enabled = False


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(ns_module, "SessionLocal", TestSession)
    monkeypatch.setattr(notification_service, "_load_config", lambda: _StubConfig())
    monkeypatch.setattr(notification_service, "_configure_email_service", lambda cfg: None)
    captured: dict = {}

    def _capture(summary):
        captured.update(summary)
        return True, "ok"

    monkeypatch.setattr(notification_service, "_send_daily_summary_email", _capture)

    db = TestSession()
    node = Node(name="px1", hostname="10.0.0.1")
    db.add(node)
    db.commit()
    db.add_all([
        SyncJob(name="replica-web", source_node_id=node.id, dest_node_id=node.id,
                source_dataset="rpool/data/vm-100-disk-0", dest_dataset="rpool/replica",
                vm_id=100, vm_name="web01"),
        HostBackupJob(name="hostbk-px1", node_id=node.id, dest_path="/var/backups/x",
                      last_backup_size=2048),
        NasSyncJob(name="nas-docs", source_endpoint_id=1, dest_endpoint_id=2,
                   source_paths=["/Condivisa/docs"], dest_base_path="/share/DATI",
                   last_run_status="success", last_run_at=datetime(2026, 7, 23, 3, 0)),
        VmSnapshotJob(name="snap-daily", label="daily", keep=7,
                      run_state={"results": [{"vmid": 100}], "summary": {"pruned_total": 2}},
                      last_run_status="success", last_run_at=datetime(2026, 7, 23, 3, 5)),
        FileEndpoint(name="syno", endpoint_type=FileEndpointType.SYNOLOGY, host="1",
                     port=1, protocol="api", username="u"),
        FileEndpoint(name="qnap", endpoint_type=FileEndpointType.QNAP, host="2",
                     port=1, protocol="api", username="u"),
    ])
    db.commit()
    db.close()
    return captured


def test_daily_summary_covers_all_modules(env):
    captured = env
    result = asyncio.run(notification_service.send_daily_summary())
    assert result["sent"] is True
    jobs = captured["jobs"]
    types = {j["type"] for j in jobs}
    assert types == {"sync", "host_backup", "nas_sync", "vm_snapshot"}
    assert captured["total_jobs"] == 4

    by_type = {j["type"]: j for j in jobs}
    assert by_type["sync"]["vm_name"] == "web01"
    assert by_type["sync"]["vm_id"] == 100
    assert by_type["host_backup"]["last_transferred"] == "2.0 KB"
    assert by_type["nas_sync"]["source_node"] == "syno"
    assert by_type["nas_sync"]["dest_node"] == "qnap"
    assert by_type["vm_snapshot"]["source_dataset"] == "label daily"
    assert "keep 7" in by_type["vm_snapshot"]["dest_dataset"]
