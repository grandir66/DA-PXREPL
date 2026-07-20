"""Engine rclone SMB↔SMB v2: output JSON strutturato, sorgente/destinazione generiche.

Usato quando il motore diretto non è disponibile (tipicamente sorgente Windows).
I dati transitano dal container dapx (limite noto e documentato).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import tempfile
from typing import Callable, Optional

from database import FileEndpoint, FileEndpointType
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import parse_synology_share_path
from services.nas_sync.engine_direct_rsync import (
    EngineCancelled,
    EngineError,
    StepResult,
)
from services.nas_sync.events import SyncEvent, human_bytes

logger = logging.getLogger(__name__)


def _obscure(password: str) -> str:
    import subprocess

    proc = subprocess.run(
        ["rclone", "obscure", password], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise EngineError(f"rclone obscure fallito: {proc.stderr.strip()}")
    return proc.stdout.strip()


def build_rclone_config(source: FileEndpoint, dest: FileEndpoint) -> tuple[str, str, str]:
    spass = decrypt_password(source.password_enc or "")
    dpass = decrypt_password(dest.password_enc or "")
    if not spass or not dpass:
        raise EngineError("Password mancante su endpoint sorgente o destinazione (SMB)")

    fd, cfg_path = tempfile.mkstemp(prefix="dapx-nas2-rclone-", suffix=".conf")
    os.close(fd)
    os.chmod(cfg_path, 0o600)

    def _section(name: str, ep: FileEndpoint, password: str) -> str:
        lines = [
            f"[{name}]",
            "type = smb",
            f"host = {ep.host}",
            f"user = {ep.username}",
            f"pass = {_obscure(password)}",
            "use_signing = false",
            "use_server_modtime = true",
        ]
        if ep.endpoint_type == FileEndpointType.WINDOWS and ep.domain:
            lines.append(f"domain = {ep.domain}")
        return "\n".join(lines) + "\n"

    content = _section("nas2_source", source, spass) + "\n" + _section("nas2_dest", dest, dpass)
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return cfg_path, "nas2_source", "nas2_dest"


def build_rclone_cmd(
    src_remote_path: str,
    dest_remote_path: str,
    *,
    delete_on_dest: bool,
    size_only: bool,
    bandwidth_limit_kb: int | None,
    filter_file: str | None,
    extra_excludes: list[str] | None = None,
) -> list[str]:
    cmd = [
        "rclone",
        "sync" if delete_on_dest else "copy",
        src_remote_path,
        dest_remote_path,
        "--create-empty-src-dirs",
        "--modify-window", "2s",
        "--fast-list",
        "--use-json-log",
        "--stats", "5s",
        "-v",
    ]
    if delete_on_dest:
        cmd.append("--delete-after")
    else:
        cmd.append("--no-traverse")
    if size_only:
        cmd.append("--size-only")
    if bandwidth_limit_kb:
        cmd.extend(["--bwlimit", f"{int(bandwidth_limit_kb)}K"])
    if filter_file:
        cmd.extend(["--filter-from", filter_file, "--ignore-case"])
    for name in extra_excludes or []:
        # Esclude cartella di 1° livello già gestita da uno step dedicato.
        cmd.extend(["--exclude", f"/{name}/**"])
        cmd.extend(["--exclude", f"/{name}"])
    return cmd


def parse_rclone_json_line(line: str) -> SyncEvent | None:
    text = line.strip()
    if not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None

    msg = str(obj.get("msg") or "")
    target = obj.get("object")
    if target:
        if msg.startswith("Copied (new)"):
            return SyncEvent(phase="copying", files_new=1, last_file=str(target), raw_line=text)
        if msg.startswith("Copied"):
            return SyncEvent(phase="copying", files_replaced=1, last_file=str(target), raw_line=text)
        if msg.startswith("Unchanged skipping") or "Updated modification time" in msg:
            return SyncEvent(files_skipped=1, last_file=str(target), raw_line=text)
        if msg.startswith("Deleted"):
            return SyncEvent(files_deleted=1, last_file=str(target), raw_line=text)

    stats = obj.get("stats")
    if isinstance(stats, dict):
        bytes_done = int(stats.get("bytes") or 0)
        bytes_total = int(stats.get("totalBytes") or 0) or None
        percent = None
        if bytes_total:
            percent = min(100, int(bytes_done * 100 / bytes_total))
        speed = None
        if stats.get("speed"):
            speed = f"{human_bytes(int(float(stats['speed'])))}/s"
        eta = stats.get("eta")
        return SyncEvent(
            phase="copying" if bytes_done else "scanning",
            bytes_done=bytes_done or None,
            bytes_total=bytes_total,
            percent=percent,
            speed=speed,
            eta_seconds=int(eta) if eta is not None else None,
            raw_line=text,
        )
    return None


async def run_rclone_step(
    source: FileEndpoint,
    dest: FileEndpoint,
    src_path: str,
    dest_base_path: str,
    *,
    delete_on_dest: bool,
    size_only: bool,
    bandwidth_limit_kb: int | None,
    filter_file: str | None,
    on_event: Optional[Callable[[SyncEvent], None]],
    cancel_check: Optional[Callable[[], bool]],
    process_registry: list,
    extra_excludes: list[str] | None = None,
) -> StepResult:
    cfg_path, src_name, dest_name = build_rclone_config(source, dest)
    share, subpath = parse_synology_share_path(src_path)
    src_remote = f"{src_name}:{share}/{subpath}" if subpath else f"{src_name}:{share}"
    rel = src_path.strip("/")
    dest_share, dest_sub = parse_synology_share_path("/" + dest_base_path.strip("/"))
    dest_parts = [p for p in (dest_sub, rel) if p]
    dest_remote = f"{dest_name}:{dest_share}/" + "/".join(dest_parts)
    cmd = build_rclone_cmd(
        src_remote,
        dest_remote,
        delete_on_dest=delete_on_dest,
        size_only=size_only,
        bandwidth_limit_kb=bandwidth_limit_kb,
        filter_file=filter_file,
        extra_excludes=extra_excludes,
    )
    env = {**os.environ, "RCLONE_CONFIG": cfg_path}
    logger.info("nas_sync rclone: %s %s -> %s", cmd[1], src_remote, dest_remote)

    result = StepResult()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        process_registry.append(proc)
        assert proc.stdout is not None
        while True:
            if cancel_check and cancel_check():
                if proc.returncode is None and proc.pid:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        proc.terminate()
                raise EngineCancelled("Step interrotto dall'utente")
            try:
                line_b = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                if proc.returncode is not None:
                    break
                continue
            if not line_b:
                break
            line = line_b.decode(errors="replace")
            result.output_lines.append(line)
            event = parse_rclone_json_line(line)
            if event and on_event:
                on_event(event)
        await proc.wait()
        result.exit_code = proc.returncode or 0
        if result.exit_code != 0:
            tail = "".join(result.output_lines)[-1500:]
            raise EngineError(f"rclone exit {result.exit_code}: {tail}", exit_code=result.exit_code)
        return result
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass
