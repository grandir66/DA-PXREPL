"""Dimensione path sorgente Synology via SSH ``du`` (veloce e affidabile)."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import re
import shlex
from typing import Callable, Optional

from database import FileEndpoint
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.exclude_presets import browse_exclude_patterns
from services.file_replication.file_sync_service import _ssh_port
from services.file_replication.path_utils import sanitize_path, synology_ssh_path

logger = logging.getLogger(__name__)

_DU_BYTES_RE = re.compile(r"^(\d+)")


def _ssh_exec_args(endpoint: FileEndpoint) -> list[str]:
    port = _ssh_port(endpoint)
    if endpoint.ssh_key_path:
        return [
            "ssh",
            "-p",
            str(port),
            "-o",
            "StrictHostKeyChecking=no",
            "-i",
            endpoint.ssh_key_path,
        ]
    password = decrypt_password(endpoint.password_enc or "")
    if password:
        return [
            "sshpass",
            "-p",
            password,
            "ssh",
            "-p",
            str(port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]
    return ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=no"]


def is_excluded_folder_name(name: str, exclude_patterns: list[str]) -> bool:
    """True se la cartella va esclusa (es. ``#snapshot``, ``@eaDir``)."""
    if not name or name in (".", ".."):
        return True
    lower = name.lower()
    if "#snapshot" in lower or lower in ("@eadir", "#recycle", "@recycle", ".snapshot"):
        return True
    for pat in exclude_patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatchcase(name, pat):
            return True
        if fnmatch.fnmatch(lower, pat.lower()):
            return True
    return False


def _remote_volume(endpoint: FileEndpoint) -> str:
    extra = endpoint.extra_config or {}
    return str(extra.get("volume") or "volume1")


async def _ssh_run(source: FileEndpoint, remote_cmd: str) -> tuple[int, str, str]:
    host = f"{source.username}@{source.host}"
    cmd = [*_ssh_exec_args(source), host, remote_cmd]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        missing = "sshpass" if cmd[0] == "sshpass" else "ssh"
        raise RuntimeError(
            f"'{missing}' non trovato sul server dapx. "
            "Installare con: apt install openssh-client sshpass"
        ) from exc
    stdout_b, stderr_b = await proc.communicate()
    return proc.returncode or 0, stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace")


def _parse_du_bytes(stdout: str) -> int:
    line = stdout.strip().splitlines()
    if not line:
        return 0
    match = _DU_BYTES_RE.match(line[-1].strip())
    return int(match.group(1)) if match else 0


async def synology_du_bytes(source: FileEndpoint, src_path: str) -> int:
    """Byte totali su Synology per ``src_path`` (``du -sb`` via SSH)."""
    remote_path = synology_ssh_path(src_path, volume=_remote_volume(source))
    remote_cmd = f"du -sb {shlex.quote(remote_path)} 2>/dev/null | cut -f1"
    logger.info("Synology du %s", remote_path)
    code, out, err = await _ssh_run(source, remote_cmd)
    if code != 0:
        logger.warning("du Synology fallito per %s: %s", src_path, err[-500:])
        return 0
    return _parse_du_bytes(out)


async def synology_list_subdir_names(source: FileEndpoint, src_path: str) -> list[str]:
    """Nomi cartelle immediate sotto ``src_path``."""
    remote_path = synology_ssh_path(src_path, volume=_remote_volume(source))
    remote_cmd = (
        f"find {shlex.quote(remote_path)} -mindepth 1 -maxdepth 1 -type d "
        f"2>/dev/null | sed 's|.*/||'"
    )
    code, out, _err = await _ssh_run(source, remote_cmd)
    if code != 0:
        return []
    return [n.strip() for n in out.splitlines() if n.strip()]


async def synology_du_folder_catalog(
    source: FileEndpoint,
    src_path: str,
    *,
    exclude_presets: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    on_folder: Optional[Callable[[str, int, int], None]] = None,
) -> dict:
    """``du`` solo sul **primo livello** di sottocartelle (esclusi snapshot).

    Non esegue ``du`` sull'intera share: evita scan ricorsivo multi-TB.
    Il totale è la somma delle cartelle immediate incluse.

    Returns:
        folders: [{path, name, bytes}, ...] — solo figli diretti di ``src_path``
        total_bytes: somma cartelle incluse
        excluded_names: nomi saltati
    """
    ui_root = sanitize_path(src_path)
    exclude = browse_exclude_patterns(exclude_presets or [])
    for pat in exclude_patterns or []:
        p = (pat or "").strip()
        if p and p not in exclude:
            exclude.append(p)

    subdirs = await synology_list_subdir_names(source, src_path)
    included: list[dict] = []
    excluded_names: list[str] = []
    total = 0
    idx = 0
    to_scan = [n for n in subdirs if not is_excluded_folder_name(n, exclude)]
    excluded_names = [n for n in subdirs if is_excluded_folder_name(n, exclude)]

    for name in to_scan:
        idx += 1
        folder_ui = sanitize_path(f"{ui_root.rstrip('/')}/{name}")
        nbytes = await synology_du_bytes(source, folder_ui)
        if on_folder:
            on_folder(name, idx, len(to_scan))
        if nbytes > 0:
            included.append({"path": folder_ui, "name": name, "bytes": nbytes})
            total += nbytes

    # Share piatta (nessuna sottocartella al primo livello): un solo du sul path.
    if not included and not excluded_names:
        root_bytes = await synology_du_bytes(source, ui_root)
        if root_bytes:
            included.append({"path": ui_root, "name": "(root)", "bytes": root_bytes})
            total = root_bytes

    included.sort(key=lambda x: int(x.get("bytes") or 0), reverse=True)
    return {
        "source_path": ui_root,
        "folders": included,
        "total_bytes": total,
        "excluded_names": excluded_names,
        "folder_count": len(included),
    }
