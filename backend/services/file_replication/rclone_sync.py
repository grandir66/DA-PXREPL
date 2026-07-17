"""Sync incrementale Synology → QNAP via rclone (SMB → SFTP)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from typing import Optional

from database import FileEndpoint
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import parse_synology_share_path

logger = logging.getLogger(__name__)

_TRANSFER_RE = re.compile(
    r"Transferred:\s+([\d.]+\s*\w+)(?:\s*/\s*([\d.]+\s*\w+))?,?\s+(\d+)%",
)


def preflight_rclone() -> None:
    from shutil import which

    if not which("rclone"):
        raise RuntimeError(
            "rclone non installato sul server dapx. Installare con: apt install rclone"
        )


def _obscure_password(password: str) -> str:
    import subprocess

    proc = subprocess.run(
        ["rclone", "obscure", password],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rclone obscure fallito: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _build_rclone_config(source: FileEndpoint, dest: FileEndpoint) -> tuple[str, str, str]:
    """Ritorna path config temp, remote sorgente, remote dest."""
    spass = decrypt_password(source.password_enc or "")
    dpass = decrypt_password(dest.password_enc or "")
    if not spass or not dpass:
        raise RuntimeError("Password mancante su endpoint sorgente o destinazione")

    fd, cfg_path = tempfile.mkstemp(prefix="dapx-fr-rclone-", suffix=".conf")
    os.close(fd)
    os.chmod(cfg_path, 0o600)

    content = f"""[fr_source]
type = smb
host = {source.host}
user = {source.username}
pass = {_obscure_password(spass)}
use_signing = false

[fr_dest]
type = sftp
host = {dest.host}
user = {dest.username}
pass = {_obscure_password(dpass)}
shell_type = unix
"""
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return cfg_path, "fr_source", "fr_dest"


def _remote_paths(src_path: str, dest_dir: str) -> tuple[str, str]:
    share, subpath = parse_synology_share_path(src_path)
    src_remote = f"{share}/{subpath}" if subpath else share
    dest_remote = dest_dir.strip("/")
    return src_remote, dest_remote


def parse_rclone_progress(line: str) -> Optional[dict]:
    match = _TRANSFER_RE.search(line)
    if not match:
        return None
    return {
        "bytes_transferred": None,
        "percent": f"{match.group(3)}%",
        "speed": None,
    }


async def rclone_sync_synology_to_qnap(
    source: FileEndpoint,
    dest: FileEndpoint,
    src_path: str,
    dest_dir: str,
    *,
    delete_on_dest: bool,
    exclude_file: str | None = None,
    bandwidth_limit_kb: int | None = None,
) -> tuple[list[str], list[str]]:
    """Sync incrementale; con delete_on_dest rimuove su QNAP ciò che non è più in sorgente."""
    cfg_path, src_name, dest_name = _build_rclone_config(source, dest)
    src_remote, dest_remote = _remote_paths(src_path, dest_dir)
    cmd = [
        "rclone",
        "sync" if delete_on_dest else "copy",
        f"{src_name}:{src_remote}",
        f"{dest_name}:{dest_remote}",
        "--stats-one-line",
        "--stats",
        "5s",
        "-v",
    ]
    if delete_on_dest:
        cmd.append("--delete-after")
    if exclude_file and os.path.isfile(exclude_file):
        cmd.extend(["--exclude-from", exclude_file])
    if bandwidth_limit_kb:
        cmd.extend(["--bwlimit", f"{bandwidth_limit_kb}K"])

    env = os.environ.copy()
    env["RCLONE_CONFIG"] = cfg_path
    logger.info(
        "rclone %s %s:%s -> %s:%s (delete=%s)",
        cmd[1],
        src_name,
        src_remote,
        dest_name,
        dest_remote,
        delete_on_dest,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        combined: list[str] = []
        assert proc.stdout is not None
        while True:
            line_b = await proc.stdout.readline()
            if not line_b:
                break
            line = line_b.decode(errors="replace")
            combined.append(line)
        code = await proc.wait()
        if code != 0:
            raise RuntimeError(f"rclone exit {code}: {''.join(combined)[-2000:]}")
        return combined, []
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass
