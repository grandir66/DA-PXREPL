"""Pull sorgente Synology via mount SMB/CIFS (rsync SSH Synology non supporta lettura)."""

from __future__ import annotations

import asyncio
import logging
import os

from database import FileEndpoint
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import parse_synology_share_path

logger = logging.getLogger(__name__)


def preflight_synology_smb() -> None:
    if not os.path.exists("/sbin/mount.cifs") and not os.path.exists("/usr/sbin/mount.cifs"):
        raise RuntimeError(
            "cifs-utils non installato sul server dapx (pull Synology via SMB). "
            "Installare con: apt install cifs-utils"
        )


def _write_credentials_file(path: str, username: str, password: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"username={username}\n")
        fh.write(f"password={password}\n")
    os.chmod(path, 0o600)


async def _run_mount(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    if proc.returncode != 0:
        err = stderr_b.decode(errors="replace").strip() or stdout_b.decode(errors="replace").strip()
        raise RuntimeError(f"mount CIFS fallito: {err}")


async def mount_synology_share(
    source: FileEndpoint,
    share: str,
    mount_point: str,
    creds_file: str,
) -> None:
    password = decrypt_password(source.password_enc or "")
    if not password:
        raise RuntimeError(f"Password mancante per endpoint Synology {source.name}")
    os.makedirs(mount_point, exist_ok=True)
    _write_credentials_file(creds_file, source.username, password)
    unc = f"//{source.host}/{share}"
    opts = f"credentials={creds_file},vers=3.0,ro,iocharset=utf8"
    await _run_mount(["mount", "-t", "cifs", unc, mount_point, "-o", opts])
    logger.info("Synology SMB montato: %s -> %s", unc, mount_point)


async def unmount_synology_share(mount_point: str) -> None:
    if not os.path.ismount(mount_point):
        return
    proc = await asyncio.create_subprocess_exec(
        "umount",
        mount_point,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


def local_source_dir(mount_point: str, subpath: str) -> str:
    base = mount_point.rstrip("/")
    if subpath:
        return f"{base}/{subpath.strip('/')}/"
    return f"{base}/"


def describe_synology_pull(src_path: str) -> tuple[str, str, str]:
    """Ritorna share, subpath, descrizione per log."""
    share, subpath = parse_synology_share_path(src_path)
    desc = f"//share/{share}"
    if subpath:
        desc += f"/{subpath}"
    return share, subpath, desc
