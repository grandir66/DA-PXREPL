"""Motore diretto: rsync eseguito via SSH sulla sorgente, push verso rsyncd destinazione.

I dati viaggiano sorgente→destinazione senza transitare da dapx.
Sicurezza: password SSH via env SSHPASS (sshpass -e); password modulo rsync
via stdin remoto → RSYNC_PASSWORD. Mai credenziali in argv o nei log.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import signal
from dataclasses import dataclass, field
from typing import Callable, Optional

from database import FileEndpoint, FileEndpointType
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import normalize_synology_ssh_path, sanitize_path
from services.nas_sync.events import SyncEvent

logger = logging.getLogger(__name__)

_PID_MARKER = "__DAPX_PID__"

RSYNC_WARNING_EXITS = (23, 24)
RSYNC_EXIT_HINTS: dict[int, str] = {
    1: "Errore di sintassi rsync (bug interno: aprire un issue).",
    5: "Autenticazione al modulo rsync fallita: verifica utente/password del servizio rsync sul NAS di destinazione.",
    10: "Errore socket verso il demone rsync di destinazione: verifica che il servizio rsync sia attivo e la porta raggiungibile.",
    11: "Errore I/O file: spazio disco o permessi sulla destinazione.",
    12: "Errore di protocollo rsync: versioni rsync incompatibili tra sorgente e destinazione.",
    30: "Timeout di rete durante il trasferimento.",
    35: "Timeout in attesa del demone rsync di destinazione.",
    255: "Connessione SSH alla sorgente fallita: verifica host, porta, credenziali SSH.",
}

_PROGRESS2_RE = re.compile(
    r"^\s*([\d,]+)\s+(\d+)%\s+([\d.]+\s?[KMGT]?B/s)\s+(\d+):(\d{2}):(\d{2})"
)
_ITEMIZE_RE = re.compile(r"^([<>ch.*][fdLDS])([+.cstTpoguax?]{7,10})\s(.+)$")
_DELETING_RE = re.compile(r"^\*deleting\s+(.+)$")


def _ssh_port(ep: FileEndpoint) -> int:
    extra = ep.extra_config or {}
    if extra.get("ssh_port") is not None:
        return int(extra["ssh_port"])
    if ep.protocol == "ssh":
        return ep.port or 22
    return 22


def build_source_fs_path(source: FileEndpoint, src_path: str) -> str:
    """Path filesystem del percorso sorgente, visto da shell SSH sulla sorgente."""
    clean = sanitize_path(src_path)
    if source.endpoint_type == FileEndpointType.SYNOLOGY:
        extra = source.extra_config or {}
        vol = extra.get("synology_volume") or extra.get("ssh_volume") or "volume1"
        return normalize_synology_ssh_path(clean, vol).rstrip("/") + "/"
    if source.endpoint_type == FileEndpointType.QNAP:
        return f"/share{clean}".rstrip("/") + "/"
    base = (source.base_path or "").rstrip("/")
    return f"{base}{clean}".rstrip("/") + "/"


def _rel_under_rsync_module(module: str, dest_subpath: str) -> str:
    """Path relativo alla root del modulo rsyncd.

    UI usa path filesystem tipo ``/share/DATI`` o ``/share/DATI/subdir``, ma
    con modulo ``DATI`` la root rsync è già quella share: non ripetere
    ``share/DATI`` nell'URL (altrimenti mkdir fallisce sul receiver).
    """
    parts = [p for p in dest_subpath.strip().strip("/").split("/") if p]
    if parts and parts[0] == "share":
        parts = parts[1:]
    if parts and parts[0] == module:
        parts = parts[1:]
    return "/".join(parts)


def build_dest_rsync_url(dest: FileEndpoint, src_path: str, dest_subpath: str) -> str:
    """URL rsyncd destinazione: rsync://user@host:port/MODULE/[subpath/]<struttura sorgente>/"""
    extra = dest.extra_config or {}
    module = str(extra.get("rsync_module") or "").strip("/")
    if not module:
        raise ValueError("Endpoint destinazione senza rsync_module configurato")
    user = str(extra.get("rsync_user") or dest.username)
    port = int(extra.get("rsync_port") or 873)
    rel = sanitize_path(src_path).strip("/")
    base_rel = _rel_under_rsync_module(module, dest_subpath or "")
    parts = [p for p in (base_rel, rel) if p]
    sub = "/".join(parts)
    return f"rsync://{user}@{dest.host}:{port}/{module}/{sub}/"


def build_remote_rsync_script(
    fs_src: str,
    dest_url: str,
    *,
    exclude_lines: list[str],
    delete_on_dest: bool,
    bandwidth_limit_kb: int | None,
) -> str:
    """Script eseguito via SSH sulla sorgente. Legge da stdin la password modulo."""
    parts = [
        "rsync",
        "-a",
        "--info=progress2",
        # Quotare: altrimenti la shell spezza su spazio e `%n` diventa un path arg.
        "--out-format='%i %n'",
        "--partial-dir=.dapx-partial",
    ]
    for pattern in exclude_lines:
        escaped = pattern.replace("'", "'\\''")
        parts.extend(["--exclude", f"'{escaped}'"])
    if bandwidth_limit_kb:
        parts.append(f"--bwlimit={int(bandwidth_limit_kb)}")
    if delete_on_dest:
        parts.append("--delete-after")
    parts.append(shlex.quote(fs_src))
    parts.append(shlex.quote(dest_url))
    rsync_cmd = " ".join(parts)
    return (
        "IFS= read -r RSYNC_PASSWORD; export RSYNC_PASSWORD; "
        'echo "__DAPX_PID__$$"; '
        f"exec {rsync_cmd}"
    )


def build_ssh_argv(source: FileEndpoint) -> tuple[list[str], dict]:
    """argv per la sessione SSH dapx→sorgente + env extra. Mai password in argv."""
    port = _ssh_port(source)
    argv = ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new"]
    env: dict = {}
    if source.ssh_key_path:
        argv.extend(["-i", source.ssh_key_path, "-o", "BatchMode=yes"])
    else:
        password = decrypt_password(source.password_enc or "")
        if password:
            argv = ["sshpass", "-e", *argv]
            env["SSHPASS"] = password
    argv.append(f"{source.username}@{source.host}")
    return argv, env


def _eta_to_seconds(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def parse_rsync_line(line: str) -> SyncEvent | None:
    """Parsa una riga di output rsync (progress2, itemize %i %n, *deleting)."""
    text = line.rstrip("\r\n")
    if not text.strip():
        return None

    deleting = _DELETING_RE.match(text.strip())
    if deleting:
        return SyncEvent(files_deleted=1, last_file=deleting.group(1).strip(), raw_line=text)

    progress = _PROGRESS2_RE.match(text)
    if progress:
        return SyncEvent(
            phase="copying",
            bytes_done=int(progress.group(1).replace(",", "")),
            percent=int(progress.group(2)),
            speed=progress.group(3).replace(" ", ""),
            eta_seconds=_eta_to_seconds(progress.group(4), progress.group(5), progress.group(6)),
            raw_line=text,
        )

    itemize = _ITEMIZE_RE.match(text)
    if itemize:
        kind = itemize.group(1)
        flags = itemize.group(2)
        name = itemize.group(3).strip()
        if kind[1] != "f":  # directory, symlink, device: non contati
            return None
        if kind[0] not in "<>":
            return None
        if "+" in flags:
            return SyncEvent(phase="copying", files_new=1, last_file=name, raw_line=text)
        return SyncEvent(phase="copying", files_replaced=1, last_file=name, raw_line=text)

    return None


class EngineError(RuntimeError):
    """Errore fatale engine (exit code rsync mappato in RSYNC_EXIT_HINTS)."""

    def __init__(self, message: str, exit_code: int | None = None):
        super().__init__(message)
        self.exit_code = exit_code


class EngineCancelled(Exception):
    """Step interrotto su richiesta utente."""


@dataclass
class StepResult:
    output_lines: list[str] = field(default_factory=list)
    exit_code: int = 0
    warnings: list[str] = field(default_factory=list)
    remote_pid: int | None = None


def _module_password(dest: FileEndpoint) -> str:
    extra = dest.extra_config or {}
    enc = extra.get("rsync_password_enc") or ""
    if enc:
        return decrypt_password(enc)
    return ""


async def kill_remote_rsync(source: FileEndpoint, pid: int) -> bool:
    """Termina il process group rsync sulla sorgente via SSH. Best effort."""
    argv, env = build_ssh_argv(source)
    cmd = argv + [f"kill -TERM -- -{pid} 2>/dev/null || kill -TERM {pid} 2>/dev/null || true"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, **env},
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
        return proc.returncode == 0
    except (OSError, asyncio.TimeoutError):
        return False


async def _terminate_local(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None and proc.pid:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        await asyncio.sleep(0.5)
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()


async def run_direct_rsync(
    source: FileEndpoint,
    dest: FileEndpoint,
    src_path: str,
    dest_subpath: str,
    *,
    exclude_lines: list[str],
    delete_on_dest: bool,
    bandwidth_limit_kb: int | None,
    on_event: Optional[Callable[[SyncEvent], None]],
    cancel_check: Optional[Callable[[], bool]],
    process_registry: list,
    argv_override: list[str] | None = None,
) -> StepResult:
    """Esegue rsync sulla sorgente via SSH; stdout/stderr → SyncEvent via on_event."""
    fs_src = build_source_fs_path(source, src_path)
    dest_url = build_dest_rsync_url(dest, src_path, dest_subpath)
    script = build_remote_rsync_script(
        fs_src,
        dest_url,
        exclude_lines=exclude_lines,
        delete_on_dest=delete_on_dest,
        bandwidth_limit_kb=bandwidth_limit_kb,
    )
    if argv_override is not None:
        argv, env = list(argv_override), {}
    else:
        argv, env = build_ssh_argv(source)
    cmd = argv + [script]
    logger.info("nas_sync direct: rsync %s -> %s (via ssh %s)", fs_src, dest_url, source.host)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **env},
        start_new_session=True,
    )
    process_registry.append(proc)
    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write((_module_password(dest) + "\n").encode())
        await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError):
        pass

    result = StepResult()
    cancelled = False
    while True:
        if cancel_check and cancel_check() and not cancelled:
            cancelled = True
            if result.remote_pid:
                await kill_remote_rsync(source, result.remote_pid)
            await _terminate_local(proc)
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
        stripped = line.strip()
        if stripped.startswith(_PID_MARKER):
            try:
                result.remote_pid = int(stripped[len(_PID_MARKER):])
            except ValueError:
                pass
            continue
        event = parse_rsync_line(line)
        if event and on_event:
            on_event(event)

    await proc.wait()
    result.exit_code = proc.returncode or 0

    if result.exit_code in RSYNC_WARNING_EXITS:
        result.warnings.append(
            "rsync ha segnalato file saltati o spariti durante la copia "
            f"(exit {result.exit_code}): controllare il log per l'elenco."
        )
        return result
    if result.exit_code != 0:
        hint = RSYNC_EXIT_HINTS.get(
            result.exit_code, f"rsync terminato con codice {result.exit_code}."
        )
        tail = "".join(result.output_lines)[-1500:]
        raise EngineError(f"{hint}\n{tail}", exit_code=result.exit_code)
    return result
