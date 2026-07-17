"""Pull sorgente Synology via SMB (smbclient — funziona anche in LXC unprivileged)."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile

from database import FileEndpoint
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import parse_synology_share_path

logger = logging.getLogger(__name__)


def preflight_synology_smb() -> None:
    from shutil import which

    if not which("smbclient"):
        raise RuntimeError(
            "smbclient non installato sul server dapx (pull Synology via SMB). "
            "Installare con: apt install smbclient"
        )


def _write_smb_credentials(path: str, username: str, password: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[global]\n")
        fh.write(f"username = {username}\n")
        fh.write(f"password = {password}\n")
    os.chmod(path, 0o600)


async def pull_synology_share(
    source: FileEndpoint,
    share: str,
    subpath: str,
    local_dir: str,
) -> tuple[list[str], list[str]]:
    """Scarica share/cartella Synology in local_dir con smbclient mget."""
    password = decrypt_password(source.password_enc or "")
    if not password:
        raise RuntimeError(f"Password mancante per endpoint Synology {source.name}")

    os.makedirs(local_dir, exist_ok=True)
    fd, creds_file = tempfile.mkstemp(prefix="dapx-fr-smb-", suffix=".cred")
    os.close(fd)
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    try:
        _write_smb_credentials(creds_file, source.username, password)
        remote = f"//{source.host}/{share}"
        smb_cmd = "prompt OFF; recurse ON; mget *"
        cmd = ["smbclient", remote]
        if subpath:
            cmd.extend(["-D", subpath])
        cmd.extend(["-A", creds_file, "-c", smb_cmd])

        logger.info(
            "Synology SMB pull %s/%s -> %s",
            share,
            subpath or ".",
            local_dir,
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=local_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        if stdout_b:
            stdout_lines.append(stdout_b.decode(errors="replace"))
        if stderr_b:
            stderr_lines.append(stderr_b.decode(errors="replace"))

        if proc.returncode != 0:
            err = "".join(stderr_lines)[-2000:] or "".join(stdout_lines)[-2000:]
            raise RuntimeError(f"smbclient exit {proc.returncode}: {err}")

        return stdout_lines, stderr_lines
    finally:
        if os.path.exists(creds_file):
            try:
                os.unlink(creds_file)
            except OSError:
                pass


def describe_synology_pull(src_path: str) -> tuple[str, str, str]:
    """Ritorna share, subpath, descrizione per log."""
    share, subpath = parse_synology_share_path(src_path)
    desc = f"//{share}"
    if subpath:
        desc += f"/{subpath}"
    return share, subpath, desc
