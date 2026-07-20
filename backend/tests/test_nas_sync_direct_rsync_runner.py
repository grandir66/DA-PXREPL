"""Test runner motore diretto con processo locale simulato (bash al posto di ssh)."""

import asyncio

import pytest

from database import FileEndpoint, FileEndpointType
from services.nas_sync.engine_direct_rsync import (
    EngineCancelled,
    EngineError,
    run_direct_rsync,
)


def _src():
    return FileEndpoint(
        name="s", endpoint_type=FileEndpointType.SYNOLOGY, host="10.0.0.1",
        port=5001, protocol="api", username="admin", password_enc=None,
        ssh_key_path="/tmp/fake_key", extra_config={},
    )


def _dst():
    return FileEndpoint(
        name="d", endpoint_type=FileEndpointType.QNAP, host="10.0.0.2",
        port=8080, protocol="api", username="admin", password_enc=None,
        extra_config={"rsync_module": "DATI"},
    )


def _fake_ssh(body: str) -> list[str]:
    """argv che ignora lo script remoto appeso e esegue `body` in bash locale."""
    return ["bash", "-c", body, "fake-ssh"]


def test_runner_collects_events_and_pid():
    events = []
    fake = _fake_ssh(
        'read -r _pw; echo "__DAPX_PID__4242"; '
        "echo '>f+++++++++ docs/a.txt'; echo '>f.st...... docs/b.txt'; exit 0"
    )
    result = asyncio.run(
        run_direct_rsync(
            _src(), _dst(), "/Condivisa/docs", "",
            exclude_lines=[], delete_on_dest=False, bandwidth_limit_kb=None,
            on_event=events.append, cancel_check=None, process_registry=[],
            argv_override=fake,
        )
    )
    assert result.exit_code == 0
    assert result.remote_pid == 4242
    assert sum(e.files_new for e in events) == 1
    assert sum(e.files_replaced for e in events) == 1


def test_runner_warning_exit_24_is_success_with_warning():
    fake = _fake_ssh('read -r _pw; echo "__DAPX_PID__1"; exit 24')
    result = asyncio.run(
        run_direct_rsync(
            _src(), _dst(), "/Condivisa/docs", "",
            exclude_lines=[], delete_on_dest=False, bandwidth_limit_kb=None,
            on_event=None, cancel_check=None, process_registry=[],
            argv_override=fake,
        )
    )
    assert result.exit_code == 24
    assert result.warnings


def test_runner_fatal_exit_raises_engine_error_with_hint():
    fake = _fake_ssh('read -r _pw; echo "__DAPX_PID__1"; echo "auth failed" >&2; exit 5')
    with pytest.raises(EngineError) as exc:
        asyncio.run(
            run_direct_rsync(
                _src(), _dst(), "/Condivisa/docs", "",
                exclude_lines=[], delete_on_dest=False, bandwidth_limit_kb=None,
                on_event=None, cancel_check=None, process_registry=[],
                argv_override=fake,
            )
        )
    assert exc.value.exit_code == 5
    assert "modulo rsync" in str(exc.value)


def test_runner_cancel_raises_cancelled():
    fake = _fake_ssh('read -r _pw; echo "__DAPX_PID__1"; sleep 30')
    with pytest.raises(EngineCancelled):
        asyncio.run(
            run_direct_rsync(
                _src(), _dst(), "/Condivisa/docs", "",
                exclude_lines=[], delete_on_dest=False, bandwidth_limit_kb=None,
                on_event=None, cancel_check=lambda: True, process_registry=[],
                argv_override=fake,
            )
        )
