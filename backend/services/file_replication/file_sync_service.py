"""Costruzione comandi rsync e parsing progresso."""

from __future__ import annotations

import re
from typing import Optional

from database import FileEndpoint, FileEndpointType, FileReplicationJob
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import normalize_synology_ssh_path

_PROGRESS_RE = re.compile(
    r"(\d+(?:,\d+)*)\s+(\d+(?:\.\d+)?%)\s+([\d.]+\w+/s)?",
)


def parse_rsync_progress(line: str) -> Optional[dict]:
    match = _PROGRESS_RE.search(line)
    if not match:
        return None
    bytes_raw = match.group(1).replace(",", "")
    try:
        bytes_val = int(bytes_raw)
    except ValueError:
        bytes_val = None
    return {
        "bytes_transferred": bytes_val,
        "percent": match.group(2),
        "speed": match.group(3),
    }


def _ssh_port(endpoint: FileEndpoint) -> int:
    """Porta SSH per rsync: distinta dalla porta API (5001/8080/443) su Synology/QNAP."""
    extra = endpoint.extra_config or {}
    if extra.get("ssh_port") is not None:
        return int(extra["ssh_port"])
    if endpoint.protocol == "ssh":
        return endpoint.port or 22
    if endpoint.endpoint_type in (FileEndpointType.SYNOLOGY, FileEndpointType.QNAP):
        return 22
    return endpoint.port or 22


def _ssh_transport(endpoint: FileEndpoint) -> str:
    port = _ssh_port(endpoint)
    if endpoint.ssh_key_path:
        return f"ssh -p {port} -o StrictHostKeyChecking=no -i {endpoint.ssh_key_path}"
    password = decrypt_password(endpoint.password_enc or "")
    if password:
        return (
            f"sshpass -p {password!r} ssh -p {port} "
            f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        )
    return f"ssh -p {port} -o StrictHostKeyChecking=no"


def _remote_spec(endpoint: FileEndpoint, remote_path: str) -> str:
    path = remote_path.rstrip("/") + "/"
    return f"{endpoint.username}@{endpoint.host}:{path}"


def build_rsync_legs(
    job: FileReplicationJob,
    source: FileEndpoint,
    dest: FileEndpoint,
    exclude_file: str,
    staging_dir: str,
) -> list[list[str]]:
    """Due gambe per path: pull sorgente → staging locale, push → QNAP."""
    legs: list[list[str]] = []
    dest_base = job.dest_staging_path.rstrip("/")

    for src_path in job.source_paths or []:
        leaf = src_path.strip("/").split("/")[-1] or "data"
        local_dir = f"{staging_dir}/{leaf}/"
        dest_remote = f"{dest_base}/{leaf}/"

        pull = ["rsync", "-a", "--info=progress2", "--exclude-from", exclude_file]
        push = ["rsync", "-a", "--info=progress2"]
        if job.delete_on_dest:
            push.append("--delete")
        if job.bandwidth_limit_kb:
            pull.extend(["--bwlimit", str(job.bandwidth_limit_kb)])
            push.extend(["--bwlimit", str(job.bandwidth_limit_kb)])
        if job.extra_rsync_args:
            extra = job.extra_rsync_args.split()
            pull.extend(extra)
            push.extend(extra)

        src_remote = src_path.rstrip("/") + "/"
        if source.endpoint_type == FileEndpointType.SYNOLOGY:
            extra = source.extra_config or {}
            vol = extra.get("synology_volume") or extra.get("ssh_volume") or "volume1"
            src_remote = normalize_synology_ssh_path(src_path, vol).rstrip("/") + "/"

        if source.endpoint_type in (FileEndpointType.SYNOLOGY, FileEndpointType.QNAP):
            module = (source.extra_config or {}).get("rsync_module", "")
            if module:
                pull.append(f"rsync://{source.username}@{source.host}/{module}/{src_path.strip('/')}/")
            else:
                pull.extend(["-e", _ssh_transport(source)])
                if source.endpoint_type == FileEndpointType.SYNOLOGY:
                    pull.append("--rsync-path=/usr/bin/rsync")
                pull.append(_remote_spec(source, src_remote))
        else:
            pull.extend(["-e", _ssh_transport(source)])
            pull.append(_remote_spec(source, src_remote))

        pull.append(local_dir)

        push.extend(["-e", _ssh_transport(dest)])
        push.append(local_dir)
        push.append(_remote_spec(dest, dest_remote))

        legs.append(pull)
        legs.append(push)

    return legs
