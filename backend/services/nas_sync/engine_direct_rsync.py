"""Motore diretto: rsync eseguito via SSH sulla sorgente, push verso rsyncd destinazione.

I dati viaggiano sorgente→destinazione senza transitare da dapx.
Sicurezza: password SSH via env SSHPASS (sshpass -e); password modulo rsync
via stdin remoto → RSYNC_PASSWORD. Mai credenziali in argv o nei log.
"""

from __future__ import annotations

import re
import shlex

from database import FileEndpoint, FileEndpointType
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import normalize_synology_ssh_path, sanitize_path
from services.nas_sync.events import SyncEvent

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


def build_dest_rsync_url(dest: FileEndpoint, src_path: str, dest_subpath: str) -> str:
    """URL rsyncd destinazione: rsync://user@host:port/MODULE/[subpath/]<struttura sorgente>/"""
    extra = dest.extra_config or {}
    module = str(extra.get("rsync_module") or "").strip("/")
    if not module:
        raise ValueError("Endpoint destinazione senza rsync_module configurato")
    user = str(extra.get("rsync_user") or dest.username)
    port = int(extra.get("rsync_port") or 873)
    rel = sanitize_path(src_path).strip("/")
    parts = [p for p in (dest_subpath.strip("/"), rel) if p]
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
        "--out-format=%i %n",
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
