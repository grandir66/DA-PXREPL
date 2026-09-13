"""Helper condivisi per unit systemd dapx-unified (porta, HTTPS, venv)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_INSTALL_DIR = "/opt/dapx-unified"
DEFAULT_PORT = 8420
SYSTEMD_UNIT = Path("/etc/systemd/system/dapx-unified.service")
STATE_CONFIG = Path("/var/lib/dapx-unified/server_config.json")
LEGACY_CONFIG = Path(__file__).resolve().parent.parent / "server_config.json"


def install_dir() -> Path:
    env = os.environ.get("DAPX_INSTALL_DIR")
    if env:
        return Path(env)
    return Path(DEFAULT_INSTALL_DIR)


def certs_dir() -> Path:
    env_dir = os.environ.get("DAPX_CERTS_DIR")
    if env_dir:
        return Path(env_dir)
    state_dir = Path("/var/lib/dapx-unified/certs")
    if state_dir.parent.exists():
        return state_dir
    return install_dir() / "backend" / "certs"


def default_server_config() -> dict[str, Any]:
    return {
        "port": int(os.environ.get("DAPX_PORT", DEFAULT_PORT)),
        "ssl_enabled": os.environ.get("DAPX_SSL", "false").lower() == "true",
    }


def load_server_config() -> dict[str, Any]:
    config = default_server_config()
    for path in (STATE_CONFIG, LEGACY_CONFIG):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                saved = json.load(handle)
            if isinstance(saved, dict):
                config.update(saved)
            break
        except Exception as exc:
            logger.warning("Impossibile leggere %s: %s", path, exc)
    return config


def save_server_config(config: dict[str, Any]) -> Path:
    STATE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with STATE_CONFIG.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
    return STATE_CONFIG


def ssl_cert_paths() -> tuple[Path, Path]:
    cert_dir = certs_dir()
    return cert_dir / "server.crt", cert_dir / "server.key"


def build_exec_start(config: dict[str, Any] | None = None) -> str:
    """ExecStart con venv uvicorn; SSL solo se certificati presenti."""
    cfg = config or load_server_config()
    port = int(cfg.get("port") or DEFAULT_PORT)
    ssl_enabled = bool(cfg.get("ssl_enabled", False))
    uvicorn = install_dir() / "venv" / "bin" / "uvicorn"
    cmd = f"{uvicorn} main:app --host 0.0.0.0 --port {port} --workers 1"
    if ssl_enabled:
        cert_path, key_path = ssl_cert_paths()
        if cert_path.exists() and key_path.exists():
            cmd += f" --ssl-keyfile {key_path} --ssl-certfile {cert_path}"
        else:
            logger.warning(
                "SSL abilitato in config ma certificati mancanti (%s); avvio HTTP",
                certs_dir(),
            )
    return f"ExecStart={cmd}"


def sync_systemd_unit(config: dict[str, Any] | None = None) -> bool:
    """Allinea ExecStart/DAPX_*/log nel unit file systemd.

    Le righe `Environment="DAPX_*"` stanno in [Service]: accodate in fondo al
    file finivano sotto [Install], dove systemd le ignora con un warning a ogni
    avvio (dts-repl, 2026-09-13). Stdout e stderr vanno al journal, che ruota
    da solo: `StandardOutput=append:<file>` aveva prodotto un file da 934 MB.
    """
    if not SYSTEMD_UNIT.exists():
        logger.warning("Unit systemd non trovato: %s", SYSTEMD_UNIT)
        return False

    cfg = config or load_server_config()
    port = int(cfg.get("port") or DEFAULT_PORT)
    ssl_enabled = bool(cfg.get("ssl_enabled", False))
    cert_path, key_path = ssl_cert_paths()
    effective_ssl = ssl_enabled and cert_path.exists() and key_path.exists()
    exec_start = build_exec_start(cfg)
    env_lines = [
        f'Environment="DAPX_PORT={port}"',
        f'Environment="DAPX_SSL={str(effective_ssl).lower()}"',
    ]

    lines = SYSTEMD_UNIT.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    sezione = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if sezione == "Service":
                _chiudi_service(new_lines, env_lines)
            sezione = stripped[1:-1]
            new_lines.append(line)
            continue
        if stripped.startswith('Environment="DAPX_PORT=') or stripped.startswith('Environment="DAPX_SSL='):
            continue  # riscritte in [Service], qualunque sezione le ospitasse
        if sezione == "Service":
            if stripped.startswith("ExecStart="):
                new_lines.append(exec_start)
                continue
            if stripped.startswith("StandardOutput="):
                new_lines.append("StandardOutput=journal")
                continue
            if stripped.startswith("StandardError="):
                new_lines.append("StandardError=journal")
                continue
        new_lines.append(line)
    if sezione == "Service":
        _chiudi_service(new_lines, env_lines)

    SYSTEMD_UNIT.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True)
    logger.info("Systemd unit sincronizzato (port=%s ssl=%s)", port, effective_ssl)
    return True


def _chiudi_service(lines: list[str], env_lines: list[str]) -> None:
    """Le righe Environment vanno in coda a [Service], prima della riga vuota
    che separa la sezione successiva."""
    coda: list[str] = []
    while lines and not lines[-1].strip():
        coda.insert(0, lines.pop())
    lines.extend(env_lines)
    lines.extend(coda)


def service_access_url(config: dict[str, Any] | None = None) -> str:
    cfg = config or load_server_config()
    port = int(cfg.get("port") or DEFAULT_PORT)
    cert_path, key_path = ssl_cert_paths()
    scheme = "https" if cfg.get("ssl_enabled") and cert_path.exists() and key_path.exists() else "http"
    return f"{scheme}://127.0.0.1:{port}"
