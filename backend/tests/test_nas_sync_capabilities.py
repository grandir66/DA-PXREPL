"""Test matrice capacità e selezione engine nas_sync."""

import pytest

from database import FileEndpoint, FileEndpointType
from services.nas_sync.capabilities import (
    ENGINE_DIRECT,
    ENGINE_RCLONE,
    resolve_capabilities,
    resolve_engine,
)


def _ep(ep_type, *, password_enc="x", ssh_key=None, extra=None):
    return FileEndpoint(
        name="e",
        endpoint_type=ep_type,
        host="h",
        port=22,
        protocol="ssh",
        username="u",
        password_enc=password_enc,
        ssh_key_path=ssh_key,
        extra_config=extra or {},
    )


def test_synology_source_has_rsync_and_smb():
    caps = resolve_capabilities(_ep(FileEndpointType.SYNOLOGY))
    assert caps["rsync_source"] is True
    assert caps["smb"] is True
    assert caps["rsync_dest"] is False  # manca rsync_module


def test_qnap_dest_with_module_has_rsync_dest():
    caps = resolve_capabilities(
        _ep(FileEndpointType.QNAP, extra={"rsync_module": "DATI", "rsync_password_enc": "x"})
    )
    assert caps["rsync_dest"] is True


def test_windows_is_smb_only():
    caps = resolve_capabilities(_ep(FileEndpointType.WINDOWS))
    assert caps == {
        "rsync_source": False,
        "rsync_dest": False,
        "smb": True,
        "reasons": caps["reasons"],
    }
    assert "rsync" in caps["reasons"]["rsync_source"].lower()


def test_source_without_credentials_no_rsync_source():
    caps = resolve_capabilities(_ep(FileEndpointType.SYNOLOGY, password_enc=None))
    assert caps["rsync_source"] is False


def test_auto_picks_direct_when_both_capable():
    src = _ep(FileEndpointType.SYNOLOGY)
    dst = _ep(FileEndpointType.QNAP, extra={"rsync_module": "DATI", "rsync_password_enc": "x"})
    engine, reason = resolve_engine("auto", src, dst)
    assert engine == ENGINE_DIRECT
    assert "diretto" in reason.lower()


def test_auto_falls_back_to_rclone_for_windows_source():
    src = _ep(FileEndpointType.WINDOWS)
    dst = _ep(FileEndpointType.QNAP, extra={"rsync_module": "DATI", "rsync_password_enc": "x"})
    engine, _ = resolve_engine("auto", src, dst)
    assert engine == ENGINE_RCLONE


def test_forced_direct_raises_if_unsupported():
    src = _ep(FileEndpointType.WINDOWS)
    dst = _ep(FileEndpointType.QNAP, extra={})
    with pytest.raises(ValueError):
        resolve_engine("direct_rsync", src, dst)


def test_forced_rclone_always_allowed_for_smb_pair():
    src = _ep(FileEndpointType.SYNOLOGY)
    dst = _ep(FileEndpointType.QNAP, extra={"rsync_module": "DATI", "rsync_password_enc": "x"})
    engine, _ = resolve_engine("rclone_smb", src, dst)
    assert engine == ENGINE_RCLONE
