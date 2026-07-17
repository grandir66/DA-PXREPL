"""Sync incrementale Synology → QNAP via rclone (SMB → SMB)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from collections.abc import Callable
from typing import Optional

from database import FileEndpoint
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import parse_synology_share_path, qnap_rclone_dest_path

logger = logging.getLogger(__name__)

def _parse_rclone_count(raw: str) -> int:
    """Converte contatori rclone (es. 3.803k, 1,234) in intero."""
    text = raw.strip().replace(",", "")
    if not text:
        return 0
    mult = 1
    suffix = text[-1].lower()
    if suffix in ("k", "m", "g", "t"):
        mult = {"k": 1_000, "m": 1_000_000, "g": 1_000_000_000, "t": 1_000_000_000_000}[suffix]
        text = text[:-1]
    try:
        return int(float(text) * mult)
    except ValueError:
        return 0


_STATS_BYTES_RE = re.compile(
    r"(?:Transferred:\s+|INFO\s+:\s+)\s*"
    r"([\d.]+\s*(?:[KMGT]i?)?B)\s*/\s*([\d.]+\s*(?:[KMGT]i?)?B|\?),?\s*(\d+|-)?%?,?\s*"
    r"([\d.]+\s*(?:[KMGT]i?)?B/s)?,?\s*(?:ETA\s+([\dmswh-]+))?",
    re.IGNORECASE,
)
_STATS_FILES_RE = re.compile(
    r"Transferred:\s+([\d,.kKmMgGtT]+)\s*/\s*([\d,.kKmMgGtT]+),?\s*(\d+|-)?%?",
    re.IGNORECASE,
)
_CHECKS_RE = re.compile(
    r"Checks:\s+([\d,.kKmMgGtT]+)\s*/\s*([\d,.kKmMgGtT]+),?\s*(\d+|-)?%?",
    re.IGNORECASE,
)
_COPIED_RE = re.compile(
    r"INFO\s+:\s+(.+?):\s+Copied\s+\((new|replaced|unchanged)\)",
    re.IGNORECASE,
)
_SKIPPED_MTIME_RE = re.compile(
    r"INFO\s+:\s+(.+?):\s+Updated modification time in destination",
    re.IGNORECASE,
)
_DELETED_RE = re.compile(
    r"INFO\s+:\s+(.+?):\s+Deleted",
    re.IGNORECASE,
)
_NOTHING_TRANSFER_RE = re.compile(r"There was nothing to transfer", re.IGNORECASE)


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
type = smb
host = {dest.host}
user = {dest.username}
pass = {_obscure_password(dpass)}
use_signing = false
"""
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return cfg_path, "fr_source", "fr_dest"


def _remote_paths(src_path: str, dest_dir: str) -> tuple[str, str]:
    share, subpath = parse_synology_share_path(src_path)
    src_remote = f"{share}/{subpath}" if subpath else share
    dest_remote = qnap_rclone_dest_path(dest_dir.rstrip("/"))
    return src_remote, dest_remote


def parse_rclone_progress(line: str) -> Optional[dict]:
    """Estrae avanzamento da righe stats/copied di rclone."""
    if _NOTHING_TRANSFER_RE.search(line):
        return {"nothing_to_transfer": True}

    copied = _COPIED_RE.search(line)
    if copied:
        action = copied.group(2).lower()
        out: dict = {"last_file": copied.group(1).strip()}
        if action == "unchanged":
            out["files_skipped_delta"] = 1
        else:
            out["files_copied_delta"] = 1
        return out

    skipped = _SKIPPED_MTIME_RE.search(line)
    if skipped:
        return {
            "files_skipped_delta": 1,
            "last_file": skipped.group(1).strip(),
        }

    deleted = _DELETED_RE.search(line)
    if deleted:
        return {
            "files_deleted_delta": 1,
            "last_file": deleted.group(1).strip(),
        }

    checks_match = _CHECKS_RE.search(line)
    if checks_match:
        done = _parse_rclone_count(checks_match.group(1))
        total = _parse_rclone_count(checks_match.group(2))
        pct_raw = (checks_match.group(3) or "").strip()
        out = {
            "files_checked": done,
            "files_checked_total": total,
        }
        if pct_raw and pct_raw != "-":
            out["checks_percent"] = f"{pct_raw}%"
        elif total > 0:
            out["checks_percent"] = f"{int(done * 100 / total)}%"
        return out

    files_match = _STATS_FILES_RE.search(line)
    if files_match:
        done = _parse_rclone_count(files_match.group(1))
        total = _parse_rclone_count(files_match.group(2))
        pct_raw = (files_match.group(3) or "").strip()
        out = {
            "files_copied": done,
            "files_total": total,
        }
        if pct_raw and pct_raw != "-":
            out["percent"] = f"{pct_raw}%"
        elif total > 0:
            out["percent"] = f"{int(done * 100 / total)}%"
        return out

    bytes_match = _STATS_BYTES_RE.search(line)
    if bytes_match:
        transferred = bytes_match.group(1).strip()
        total_raw = bytes_match.group(2).strip()
        pct_raw = (bytes_match.group(3) or "").strip()
        speed = (bytes_match.group(4) or "").strip() or None
        eta = (bytes_match.group(5) or "").strip() or None
        out = {
            "transferred_human": transferred,
            "speed": speed,
            "eta": eta,
        }
        if total_raw != "?":
            out["transferred_total_human"] = total_raw
            if pct_raw and pct_raw != "-":
                out["percent"] = f"{pct_raw}%"
        return out

    return None


def merge_rclone_progress(state: dict, patch: dict) -> dict:
    """Accumula patch di progresso rclone nello stato del job."""
    merged = dict(state)
    for delta_key, counter_key in (
        ("files_copied_delta", "files_copied"),
        ("files_skipped_delta", "files_skipped"),
        ("files_deleted_delta", "files_deleted"),
    ):
        if patch.get(delta_key):
            merged[counter_key] = int(merged.get(counter_key) or 0) + int(patch[delta_key])

    if patch.get("nothing_to_transfer"):
        merged["nothing_to_transfer"] = True

    for key, value in patch.items():
        if key.endswith("_delta") or key == "nothing_to_transfer":
            continue
        if value is not None:
            merged[key] = value

    copied = int(merged.get("files_copied") or 0)
    skipped = int(merged.get("files_skipped") or 0)
    checked = merged.get("files_checked")
    if checked is not None and copied + skipped == 0 and int(checked) > 0:
        merged["files_skipped"] = max(skipped, int(checked) - copied)

    merged["files_done"] = copied
    return merged


def summarize_rclone_output(lines: list[str]) -> dict:
    """Ricostruisce riepilogo finale da tutto l'output rclone."""
    state: dict = {}
    for line in lines:
        patch = parse_rclone_progress(line)
        if patch:
            state = merge_rclone_progress(state, patch)
    return state


def format_rclone_progress_summary(state: dict) -> str:
    """Testo riepilogo per log/messaggi UI."""
    if not state:
        return ""
    parts: list[str] = []
    copied = int(state.get("files_copied") or state.get("files_done") or 0)
    skipped = int(state.get("files_skipped") or 0)
    deleted = int(state.get("files_deleted") or 0)
    checked = state.get("files_checked_total") or state.get("files_checked")

    if copied:
        parts.append(f"{copied:,} copiati".replace(",", "."))
    if skipped:
        parts.append(f"{skipped:,} saltati".replace(",", "."))
    if deleted:
        parts.append(f"{deleted:,} eliminati".replace(",", "."))
    if checked:
        parts.append(f"{int(checked):,} controllati".replace(",", "."))

    if state.get("transferred_human"):
        size = state["transferred_human"]
        if state.get("transferred_total_human"):
            size += f" / {state['transferred_total_human']}"
        parts.append(size)

    if state.get("nothing_to_transfer") and not copied:
        parts.insert(0, "Nessun file da trasferire")

    return " · ".join(parts)


async def rclone_sync_synology_to_qnap(
    source: FileEndpoint,
    dest: FileEndpoint,
    src_path: str,
    dest_dir: str,
    *,
    delete_on_dest: bool,
    filter_file: str | None = None,
    bandwidth_limit_kb: int | None = None,
    on_line: Callable[[str], None] | None = None,
) -> tuple[list[str], list[str]]:
    """Sync incrementale; con delete_on_dest rimuove su QNAP ciò che non è più in sorgente."""
    cfg_path, src_name, dest_name = _build_rclone_config(source, dest)
    src_remote, dest_remote = _remote_paths(src_path, dest_dir)
    cmd = [
        "rclone",
        "sync" if delete_on_dest else "copy",
        f"{src_name}:{src_remote}",
        f"{dest_name}:{dest_remote}",
        "--create-empty-src-dirs",
        "--stats",
        "5s",
        "-v",
    ]
    if delete_on_dest:
        cmd.append("--delete-after")
    if filter_file and os.path.isfile(filter_file):
        cmd.extend(["--filter-from", filter_file])
        cmd.append("--ignore-case")
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
        mkdir_proc = await asyncio.create_subprocess_exec(
            "rclone",
            "mkdir",
            f"{dest_name}:{dest_remote}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        mkdir_out, _ = await mkdir_proc.communicate()
        if mkdir_out:
            combined_mkdir = mkdir_out.decode(errors="replace")
            if on_line:
                on_line(combined_mkdir)

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
            if on_line:
                on_line(line)
        code = await proc.wait()
        if code != 0:
            tail = "".join(combined)[-2000:]
            if code in (-15, -2, 130, 143):
                raise RuntimeError(
                    "Sync interrotto (processo terminato). "
                    "I file già copiati restano su QNAP. "
                    "Rilancia il job: rclone trasferirà solo i file mancanti."
                ) from None
            raise RuntimeError(f"rclone exit {code}: {tail}")
        return combined, []
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass
