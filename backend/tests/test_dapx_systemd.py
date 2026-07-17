"""Test helper systemd dapx."""

from pathlib import Path

from services import dapx_systemd


def test_build_exec_start_http(tmp_path, monkeypatch):
    inst = tmp_path / "opt" / "dapx-unified"
    (inst / "venv" / "bin").mkdir(parents=True)
    uvicorn = inst / "venv" / "bin" / "uvicorn"
    uvicorn.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(dapx_systemd, "install_dir", lambda: inst)
    monkeypatch.setattr(
        dapx_systemd,
        "load_server_config",
        lambda: {"port": 8420, "ssl_enabled": False},
    )

    line = dapx_systemd.build_exec_start()
    assert line.startswith("ExecStart=")
    assert str(uvicorn) in line
    assert "--workers 1" in line
    assert "--ssl-keyfile" not in line


def test_build_exec_start_https_with_certs(tmp_path, monkeypatch):
    inst = tmp_path / "opt" / "dapx-unified"
    (inst / "venv" / "bin").mkdir(parents=True)
    (inst / "venv" / "bin" / "uvicorn").write_text("#!/bin/sh\n", encoding="utf-8")
    cert_dir = tmp_path / "var" / "lib" / "dapx-unified" / "certs"
    cert_dir.mkdir(parents=True)
    (cert_dir / "server.crt").write_text("cert", encoding="utf-8")
    (cert_dir / "server.key").write_text("key", encoding="utf-8")

    monkeypatch.setattr(dapx_systemd, "install_dir", lambda: inst)
    monkeypatch.setattr(dapx_systemd, "certs_dir", lambda: cert_dir)
    monkeypatch.setattr(
        dapx_systemd,
        "load_server_config",
        lambda: {"port": 8420, "ssl_enabled": True},
    )

    line = dapx_systemd.build_exec_start()
    assert "--ssl-keyfile" in line
    assert "--ssl-certfile" in line
    assert "/usr/bin/python3" not in line
