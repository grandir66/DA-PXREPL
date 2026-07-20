"""Test preflight nas_sync con runner SSH finto."""

import asyncio

import pytest

from database import FileEndpoint, FileEndpointType
from services.file_replication.endpoint_crypto import encrypt_password
from services.nas_sync.models import NasSyncJob
from services.nas_sync.preflight import run_preflight


@pytest.fixture(autouse=True)
def _pin_secret_key(monkeypatch):
    """Chiave fissa per la durata del test: altri test (es. test_endpoint_crypto)
    mutano os.environ e una _ENC calcolata a import time diventerebbe indecifrabile."""
    monkeypatch.setenv("DAPX_SECRET_KEY", "test-secret-key-for-testing-only")


def _enc() -> str:
    return encrypt_password("test")


def _src():
    return FileEndpoint(
        name="s", endpoint_type=FileEndpointType.SYNOLOGY, host="10.0.0.1", port=5001,
        protocol="api", username="admin", password_enc=_enc(), extra_config={},
    )


def _dst():
    return FileEndpoint(
        name="d", endpoint_type=FileEndpointType.QNAP, host="10.0.0.2", port=8080,
        protocol="api", username="admin", password_enc=_enc(),
        extra_config={"rsync_module": "DATI", "rsync_password_enc": _enc(), "rsync_port": 873},
    )


def _job(method="auto"):
    return NasSyncJob(
        name="j", source_endpoint_id=1, dest_endpoint_id=2,
        source_paths=["/Condivisa/docs"], dest_base_path="", sync_method=method,
    )


def test_preflight_all_ok():
    async def runner(argv, env, script, timeout):
        if "rsync --version" in script:
            return 0, "rsync  version 3.2.7"
        if "echo dapx-ok" in script:
            return 0, "dapx-ok"
        if "/dev/tcp/" in script or "nc -z" in script:
            return 0, "open"
        if "rsync://" in script:
            return 0, "module-ok"
        return 0, "ok"

    checks = asyncio.run(run_preflight(_job(), _src(), _dst(), ssh_runner=runner))
    by_name = {c["check"]: c for c in checks}
    assert by_name["engine"]["ok"] is True
    assert "direct" in by_name["engine"]["message"]
    assert by_name["ssh_source"]["ok"] is True
    assert by_name["rsync_source"]["ok"] is True
    assert by_name["dest_port"]["ok"] is True
    assert by_name["dest_module"]["ok"] is True


def test_preflight_ssh_failure_stops_dependent_checks():
    async def runner(argv, env, script, timeout):
        return 255, "Permission denied"

    checks = asyncio.run(run_preflight(_job(), _src(), _dst(), ssh_runner=runner))
    by_name = {c["check"]: c for c in checks}
    assert by_name["ssh_source"]["ok"] is False
    assert by_name["ssh_source"]["hint"]
    assert "rsync_source" not in by_name  # non eseguito senza SSH


def test_preflight_rclone_engine_checks_binary():
    src = FileEndpoint(
        name="w", endpoint_type=FileEndpointType.WINDOWS, host="10.0.0.3", port=445,
        protocol="smb", username="u", password_enc=_enc(), extra_config={},
    )
    checks = asyncio.run(run_preflight(_job(), src, _dst(), ssh_runner=None))
    by_name = {c["check"]: c for c in checks}
    assert by_name["engine"]["ok"] is True
    assert "rclone" in by_name["engine"]["message"]
    assert "rclone_binary" in by_name
