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


def _ssh_cmd(endpoint: FileEndpoint) -> tuple[list[str], dict[str, str]]:
    """Argv SSH + env (SSHPASS). Mai password in argv."""
    password = decrypt_password(endpoint.password_enc or "")
    port = _ssh_port(endpoint)
    if endpoint.ssh_key_path:
        return (
            [
                "ssh",
                "-p",
                str(port),
                "-o",
                "StrictHostKeyChecking=no",
                "-i",
                endpoint.ssh_key_path,
            ],
            {},
        )
    if password:
        return (
            [
                "sshpass",
                "-e",
                "ssh",
                "-p",
                str(port),
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
            ],
            {"SSHPASS": password},
        )
    return (["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=no"], {})


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

    src_ssh, src_env = _ssh_cmd(source)
    dest_ssh, dest_env = _ssh_cmd(dest)
    src_host = f"{source.username}@{source.host}"
    dest_host = f"{dest.username}@{dest.host}"

    if exclude_file and os.path.isfile(exclude_file):
        with open(exclude_file, encoding="utf-8") as fh:
            excl_body = fh.read().replace("'", "'\"'\"'")
        remote_tar = (
            f"printf '%s' '{excl_body}' > /tmp/dapx-fr-exclude.txt && "
            f"tar cf - --exclude-from=/tmp/dapx-fr-exclude.txt -C {shlex.quote(src_base)} . "
            f"&& rm -f /tmp/dapx-fr-exclude.txt"
        )
    else:
        remote_tar = f"tar cf - -C {shlex.quote(src_base)} ."

    prep_and_extract = f"mkdir -p {shlex.quote(dest_dir)} && tar xf - -C {shlex.quote(dest_dir)}"

    # Due processi separati con env propri: niente password in argv della shell.
    src_proc = await asyncio.create_subprocess_exec(
        *src_ssh,
        src_host,
        remote_tar,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **src_env} if src_env else None,
    )
    dest_proc = await asyncio.create_subprocess_exec(
        *dest_ssh,
        dest_host,
        prep_and_extract,
        stdin=src_proc.stdout,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **dest_env} if dest_env else None,
    )
    # Consenti a src di ricevere SIGPIPE se dest esce prima.
    if src_proc.stdout is not None:
        src_proc.stdout.close()

    dest_out_b, dest_err_b = await dest_proc.communicate()
    src_out_b, src_err_b = await src_proc.communicate()

    out = dest_out_b.decode(errors="replace") + src_out_b.decode(errors="replace")
    err = dest_err_b.decode(errors="replace") + src_err_b.decode(errors="replace")
    code = dest_proc.returncode or 0
    if src_proc.returncode not in (0, None) and code == 0:
        code = src_proc.returncode or 0
    if code != 0:
        raise RuntimeError(f"stream tar exit {code}: {(out + err)[-2000:]}")
    return [out], [err]
