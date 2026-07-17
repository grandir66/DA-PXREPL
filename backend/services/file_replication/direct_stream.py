"""Sync diretto Synology → QNAP via pipe tar (no staging locale su dapx)."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex

from database import FileEndpoint
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.file_sync_service import _ssh_port
from services.file_replication.path_utils import parse_synology_share_path, synology_ssh_path

logger = logging.getLogger(__name__)


def _ssh_password_args(endpoint: FileEndpoint) -> list[str]:
    password = decrypt_password(endpoint.password_enc or "")
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


async def _run_shell(cmd: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return proc.returncode or 0, out_b.decode(errors="replace"), err_b.decode(errors="replace")


async def stream_synology_to_qnap(
    source: FileEndpoint,
    dest: FileEndpoint,
    src_path: str,
    dest_dir: str,
    exclude_file: str | None = None,
) -> tuple[list[str], list[str]]:
    """Stream tar Synology → QNAP senza copia intermedia su dapx."""
    src_base = synology_ssh_path(src_path)
    dest_dir = dest_dir.rstrip("/")
    share, subpath = parse_synology_share_path(src_path)
    desc = f"{src_base} → {dest_dir}"
    logger.info("Stream tar Synology→QNAP %s", desc)

    src_ssh = " ".join(shlex.quote(p) for p in _ssh_password_args(source))
    dest_ssh = " ".join(shlex.quote(p) for p in _ssh_password_args(dest))
    src_host = f"{source.username}@{source.host}"
    dest_host = f"{dest.username}@{dest.host}"

    remote_exclude = ""
    if exclude_file and os.path.isfile(exclude_file):
        with open(exclude_file, encoding="utf-8") as fh:
            excl_body = fh.read().replace("'", "'\"'\"'")
        remote_exclude = (
            f"printf '%s' '{excl_body}' > /tmp/dapx-fr-exclude.txt && "
            f"tar cf - --exclude-from=/tmp/dapx-fr-exclude.txt -C {shlex.quote(src_base)} . "
            f"&& rm -f /tmp/dapx-fr-exclude.txt"
        )
    else:
        remote_exclude = f"tar cf - -C {shlex.quote(src_base)} ."

    prep_dest = f"mkdir -p {shlex.quote(dest_dir)}"
    tar_dest = f"tar xf - -C {shlex.quote(dest_dir)}"

    pipeline = (
        f"{src_ssh} {shlex.quote(src_host)} {shlex.quote(remote_exclude)} "
        f"| {dest_ssh} {shlex.quote(dest_host)} {shlex.quote(prep_dest + ' && ' + tar_dest)}"
    )

    code, out, err = await _run_shell(pipeline)
    combined = [out, err]
    if code != 0:
        raise RuntimeError(f"stream tar exit {code}: {(out + err)[-2000:]}")
    return combined, []
