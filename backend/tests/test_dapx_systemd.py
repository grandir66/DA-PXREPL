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


# --- sync_systemd_unit: dove finiscono le righe e dove vanno i log ----------
#
# Su dts-repl (2026-09-13) l'unit aveva le due `Environment="DAPX_*"` sotto
# [Install] — accodate in fondo al file, ignorate da systemd con un warning a
# ogni avvio — e `StandardOutput=append:` su un file che nessuno ruotava:
# 934 MB in due mesi.

_UNIT_VECCHIA = """[Unit]
Description=DAPX

[Service]
Type=simple
ExecStart=/opt/dapx-unified/venv/bin/uvicorn main:app --port 8420
Restart=always
StandardOutput=append:/var/log/dapx-unified/dapx-unified.log
StandardError=append:/var/log/dapx-unified/dapx-unified.log

[Install]
WantedBy=multi-user.target
Environment="DAPX_PORT=443"
Environment="DAPX_SSL=true"
"""


def _sezione(testo: str, nome: str) -> list[str]:
    righe, dentro = [], False
    for r in testo.splitlines():
        if r.startswith("["):
            dentro = r.strip() == f"[{nome}]"
            continue
        if dentro and r.strip():
            righe.append(r.strip())
    return righe


def _prepara(tmp_path, monkeypatch, contenuto):
    inst = tmp_path / "opt" / "dapx-unified"
    (inst / "venv" / "bin").mkdir(parents=True)
    (inst / "venv" / "bin" / "uvicorn").write_text("#!/bin/sh\n", encoding="utf-8")
    unit = tmp_path / "dapx-unified.service"
    unit.write_text(contenuto, encoding="utf-8")
    monkeypatch.setattr(dapx_systemd, "install_dir", lambda: inst)
    monkeypatch.setattr(dapx_systemd, "SYSTEMD_UNIT", unit)
    monkeypatch.setattr(dapx_systemd, "ssl_cert_paths", lambda: (tmp_path / "no.crt", tmp_path / "no.key"))
    monkeypatch.setattr(dapx_systemd.subprocess, "run", lambda *a, **k: None)
    return unit


def test_sync_unit_mette_le_environment_in_service_non_in_install(tmp_path, monkeypatch):
    unit = _prepara(tmp_path, monkeypatch, _UNIT_VECCHIA)
    assert dapx_systemd.sync_systemd_unit({"port": 8420, "ssl_enabled": False})
    testo = unit.read_text(encoding="utf-8")
    assert _sezione(testo, "Install") == ["WantedBy=multi-user.target"]
    service = _sezione(testo, "Service")
    assert 'Environment="DAPX_PORT=8420"' in service
    assert 'Environment="DAPX_SSL=false"' in service
    assert testo.count('Environment="DAPX_PORT=') == 1


def test_sync_unit_manda_stdout_e_stderr_al_journal(tmp_path, monkeypatch):
    unit = _prepara(tmp_path, monkeypatch, _UNIT_VECCHIA)
    dapx_systemd.sync_systemd_unit({"port": 8420, "ssl_enabled": False})
    service = _sezione(unit.read_text(encoding="utf-8"), "Service")
    assert "StandardOutput=journal" in service
    assert "StandardError=journal" in service
    assert not any("append:" in r for r in service)


def test_sync_unit_senza_environment_le_aggiunge_in_service(tmp_path, monkeypatch):
    unit = _prepara(tmp_path, monkeypatch, "[Unit]\nDescription=x\n\n[Service]\nExecStart=/bin/true\n\n[Install]\nWantedBy=multi-user.target\n")
    dapx_systemd.sync_systemd_unit({"port": 9000, "ssl_enabled": False})
    testo = unit.read_text(encoding="utf-8")
    assert 'Environment="DAPX_PORT=9000"' in _sezione(testo, "Service")
    assert _sezione(testo, "Install") == ["WantedBy=multi-user.target"]
