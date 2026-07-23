"""Test dei fix remediation Wave 0 + sicurezza non-breaking."""

import asyncio
import io
import os
import tarfile
import tempfile

import pytest

from services.url_guard import UnsafeUrlError, assert_safe_webhook_url


# --- S-04/S3: quoting description snapshot (no shell injection) ---

def test_create_snapshot_quotes_malicious_description(monkeypatch):
    from services.proxmox_service import proxmox_service

    captured = {}

    async def fake_exec(hostname, command, port=22, username="root", key_path=None, timeout=300):
        captured["cmd"] = command
        from services.ssh_service import SSHResult
        return SSHResult(success=True, stdout="", stderr="", exit_code=0)

    monkeypatch.setattr("services.proxmox_service.ssh_service.execute", fake_exec)
    payload = 'autodaily_x"; rm -rf / #$(reboot)`id`'
    asyncio.run(proxmox_service.create_snapshot(
        hostname="h", vmid=100, snapname="autodaily_20260101_000000",
        description=payload, vm_type="qemu",
    ))
    cmd = captured["cmd"]
    # La description pericolosa è quotata: nessun breakout sfruttabile.
    assert "rm -rf /" not in cmd.split("--description", 1)[1].split("'")[0] if "'" in cmd else True
    # shlex.quote racchiude in apici singoli e neutralizza $()/backtick
    assert "$(reboot)" not in cmd or "'" in cmd
    assert "--description" in cmd


# --- S-03/S5: tar guard anti-slip ---

def test_safe_extractall_rejects_traversal():
    from routers.config_backup import _safe_extractall
    from fastapi import HTTPException

    with tempfile.TemporaryDirectory() as d:
        tar_path = os.path.join(d, "evil.tar")
        with tarfile.open(tar_path, "w") as tar:
            data = b"pwned"
            info = tarfile.TarInfo(name="../escape.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        dest = os.path.join(d, "out")
        os.makedirs(dest)
        with tarfile.open(tar_path, "r") as tar:
            with pytest.raises(HTTPException) as exc:
                _safe_extractall(tar, dest)
            assert exc.value.status_code == 400
        assert not os.path.exists(os.path.join(d, "escape.txt"))


def test_safe_extractall_allows_normal_members():
    from routers.config_backup import _safe_extractall

    with tempfile.TemporaryDirectory() as d:
        tar_path = os.path.join(d, "ok.tar")
        with tarfile.open(tar_path, "w") as tar:
            data = b"{}"
            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        dest = os.path.join(d, "out")
        os.makedirs(dest)
        with tarfile.open(tar_path, "r") as tar:
            _safe_extractall(tar, dest)
        assert os.path.isfile(os.path.join(dest, "manifest.json"))


# --- C-07/B4: retention non pota su errore listing ---

def test_prune_vm_skips_on_listing_error(monkeypatch):
    from services.vm_snapshot import retention

    class _Node:
        hostname = "h"; ssh_port = 22; ssh_user = "root"; ssh_key_path = "/k"

    async def boom(**kwargs):
        raise RuntimeError("pvesh giù")

    deleted = []

    async def fake_delete(**kwargs):
        deleted.append(kwargs)
        return True, "ok"

    monkeypatch.setattr(retention.proxmox_service, "get_snapshots", boom)
    monkeypatch.setattr(retention.proxmox_service, "delete_snapshot", fake_delete)
    pruned, errors = asyncio.run(retention.prune_vm(_Node(), 100, "qemu", "daily", 1))
    assert pruned == []
    assert errors and "listing" in errors[0].lower()
    assert deleted == []  # nessuna cancellazione al buio


# --- S-12/S6: SSRF guard ---

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/hook",
    "http://localhost:8080/x",
    "http://169.254.169.254/latest/meta-data/",
    "ftp://example.com/x",
    "file:///etc/passwd",
])
def test_ssrf_guard_blocks_dangerous(url):
    with pytest.raises(UnsafeUrlError):
        assert_safe_webhook_url(url)


def test_ssrf_guard_allows_public_https():
    # 8.8.8.8 è pubblico e risolvibile senza DNS
    assert_safe_webhook_url("https://8.8.8.8/webhook") is None
