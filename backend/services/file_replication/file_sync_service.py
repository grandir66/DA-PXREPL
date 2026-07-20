"""Costruzione comandi rsync e parsing progresso."""

from __future__ import annotations

import re
from typing import Optional

from database import FileEndpoint, FileEndpointType, FileReplicationJob
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.path_utils import (
    normalize_synology_ssh_path,
    synology_to_qnap_dest_path,
)

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
    """Comando trasporto SSH per rsync -e. Mai password in argv: usare _ssh_env + sshpass -e."""
    port = _ssh_port(endpoint)
    if endpoint.ssh_key_path:
        return f"ssh -p {port} -o StrictHostKeyChecking=no -i {endpoint.ssh_key_path}"
    password = decrypt_password(endpoint.password_enc or "")
    if password:
        return (
            f"sshpass -e ssh -p {port} "
            f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        )
    return f"ssh -p {port} -o StrictHostKeyChecking=no"


def _ssh_env(endpoint: FileEndpoint) -> dict[str, str]:
    """Env extra per il processo rsync (SSHPASS se autenticazione a password)."""
    if endpoint.ssh_key_path:
        return {}
    password = decrypt_password(endpoint.password_enc or "")
    if password:
        return {"SSHPASS": password}
    return {}


def _remote_spec(endpoint: FileEndpoint, remote_path: str) -> str:
    path = remote_path.rstrip("/") + "/"
    return f"{endpoint.username}@{endpoint.host}:{path}"


def build_sync_plan(
    job: FileReplicationJob,
    source: FileEndpoint,
    dest: FileEndpoint,
    exclude_file: str,
    staging_dir: str,
    *,
    filter_file: str | None = None,
) -> list[dict]:
    """Piano sync per path: pull (SMB su Synology, rsync altrove) + push QNAP."""
    steps: list[dict] = []
    dest_base = job.dest_staging_path.rstrip("/")
    mirror_synology = (
        source.endpoint_type == FileEndpointType.SYNOLOGY
        and dest.endpoint_type == FileEndpointType.QNAP
    )
    use_rclone = mirror_synology and not (source.extra_config or {}).get("rsync_module")

    for src_path in job.source_paths or []:
        if mirror_synology:
            dest_remote = synology_to_qnap_dest_path(src_path, dest_base)
        else:
            leaf = src_path.strip("/").split("/")[-1] or "data"
            dest_remote = f"{dest_base}/{leaf}/"
        local_dir = f"{staging_dir}/{src_path.strip('/').replace('/', '_') or 'data'}/"

        if use_rclone:
            steps.append(
                {
                    "type": "rclone_sync",
                    "src_path": src_path,
                    "dest_dir": dest_remote,
                    "filter_file": filter_file,
                    "delete_on_dest": job.delete_on_dest,
                    "bandwidth_limit_kb": job.bandwidth_limit_kb,
                }
            )
            continue

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
            extra_cfg = source.extra_config or {}
            vol = extra_cfg.get("synology_volume") or extra_cfg.get("ssh_volume") or "volume1"
            src_remote = normalize_synology_ssh_path(src_path, vol).rstrip("/") + "/"

        module = (source.extra_config or {}).get("rsync_module", "")
        if source.endpoint_type in (FileEndpointType.SYNOLOGY, FileEndpointType.QNAP) and module:
            pull.append(f"rsync://{source.username}@{source.host}/{module}/{src_path.strip('/')}/")
            pull_env: dict[str, str] = {}
        else:
            pull.extend(["-e", _ssh_transport(source)])
            pull.append(_remote_spec(source, src_remote))
            pull_env = _ssh_env(source)
        pull.append(local_dir)
        steps.append({"type": "rsync", "cmd": pull, "env": pull_env})

        push.extend(["-e", _ssh_transport(dest)])
        push.append(local_dir)
        push.append(_remote_spec(dest, dest_remote))
        steps.append({"type": "rsync", "cmd": push, "env": _ssh_env(dest)})

    return steps


def build_rsync_legs(
    job: FileReplicationJob,
    source: FileEndpoint,
    dest: FileEndpoint,
    exclude_file: str,
    staging_dir: str,
) -> list[list[str]]:
    """Compat test: espande il piano in comandi rsync (senza SMB)."""
    cmds: list[list[str]] = []
    for step in build_sync_plan(job, source, dest, exclude_file, staging_dir):
        if step["type"] == "rsync":
            cmds.append(step["cmd"])
    return cmds
