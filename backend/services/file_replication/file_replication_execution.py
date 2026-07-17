"""Esecuzione job replica file."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime
from typing import Optional

from database import FileEndpoint, FileEndpointType, FileReplicationJob, JobLog, SessionLocal
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.exclude_presets import build_exclude_lines
from services.file_replication.file_sync_service import build_sync_plan, parse_rsync_progress
from services.file_replication.synology_smb import (
    describe_synology_pull,
    preflight_synology_smb,
    pull_synology_share,
)
from services.notification_service import notification_service

logger = logging.getLogger(__name__)

_running: set[int] = set()
_progress: dict[int, dict] = {}


def _preflight_rsync_tools(source: FileEndpoint, dest: FileEndpoint) -> None:
    if not shutil.which("rsync"):
        raise RuntimeError(
            "rsync non installato sul server dapx. Installare con: apt install rsync openssh-client"
        )

    def _needs_sshpass(ep: FileEndpoint) -> bool:
        if ep.ssh_key_path:
            return False
        return bool(decrypt_password(ep.password_enc or ""))

    if _needs_sshpass(source) or _needs_sshpass(dest):
        if not shutil.which("sshpass"):
            raise RuntimeError(
                "sshpass non installato sul server dapx (password SSH sugli endpoint). "
                "Installare con: apt install sshpass"
            )


def _write_failure_log(
    db,
    *,
    job_id: int,
    log_row: Optional[JobLog],
    job: Optional[FileReplicationJob],
    dest: Optional[FileEndpoint],
    error: str,
    duration: int,
) -> None:
    if log_row:
        log_row.status = "failed"
        log_row.error = error
        log_row.duration = duration
        log_row.completed_at = datetime.utcnow()
        return
    if not job:
        return
    db.add(
        JobLog(
            job_type="file_replication",
            job_id=job_id,
            node_name=dest.name if dest else None,
            dataset=job.dest_staging_path,
            status="failed",
            message=f"Replica fallita: {job.name}",
            error=error,
            duration=duration,
            completed_at=datetime.utcnow(),
        )
    )


def is_job_running(job_id: int) -> bool:
    return job_id in _running


def get_job_progress(job_id: int) -> Optional[dict]:
    return _progress.get(job_id)


async def execute_file_replication_job(job_id: int) -> None:
    if job_id in _running:
        logger.warning("FileReplicationJob %s già in esecuzione", job_id)
        return

    _running.add(job_id)
    _progress[job_id] = {"status": "running", "percent": "0%", "bytes_transferred": 0}
    db = SessionLocal()
    log_row: Optional[JobLog] = None
    started = datetime.utcnow()
    exclude_path: Optional[str] = None
    staging_dir: Optional[str] = None
    source: Optional[FileEndpoint] = None
    dest: Optional[FileEndpoint] = None

    try:
        job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
        if not job:
            logger.error("FileReplicationJob %s non trovato", job_id)
            return

        source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
        dest = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
        if not source or not dest:
            raise RuntimeError("Endpoint sorgente o destinazione mancante")
        if dest.endpoint_type != FileEndpointType.QNAP:
            raise RuntimeError("La destinazione deve essere un endpoint QNAP")

        _preflight_rsync_tools(source, dest)
        if source.endpoint_type == FileEndpointType.SYNOLOGY:
            preflight_synology_smb()

        job.current_status = "running"
        db.commit()

        log_row = JobLog(
            job_type="file_replication",
            job_id=job.id,
            node_name=dest.name,
            dataset=job.dest_staging_path,
            status="started",
            message=f"Avvio replica file: {job.name}",
        )
        db.add(log_row)
        db.commit()

        exclude_lines = build_exclude_lines(job.exclude_presets or [], job.exclude_patterns or [])
        fd, exclude_path = tempfile.mkstemp(prefix="dapx-fr-exclude-", suffix=".txt")
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(exclude_lines) + "\n")

        staging_dir = tempfile.mkdtemp(prefix=f"dapx-fr-{job_id}-")
        sync_plan = build_sync_plan(job, source, dest, exclude_path, staging_dir)
        combined_stdout: list[str] = []
        combined_stderr: list[str] = []
        total_bytes = 0

        async def _run_rsync(cmd: list[str]) -> None:
            nonlocal total_bytes
            logger.info("FileReplicationJob %s rsync: %s", job_id, " ".join(cmd[:8]))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                missing = cmd[0] if cmd else "rsync"
                raise RuntimeError(
                    f"'{missing}' non trovato sul server dapx. "
                    "Installare con: apt install rsync openssh-client sshpass cifs-utils"
                ) from exc
            assert proc.stderr is not None
            while True:
                line_b = await proc.stderr.readline()
                if not line_b:
                    break
                line = line_b.decode(errors="replace")
                combined_stderr.append(line)
                prog = parse_rsync_progress(line)
                if prog:
                    if prog.get("bytes_transferred"):
                        total_bytes = max(total_bytes, prog["bytes_transferred"])
                    _progress[job_id] = {
                        "status": "running",
                        "percent": prog.get("percent", _progress[job_id].get("percent")),
                        "bytes_transferred": total_bytes,
                        "speed": prog.get("speed"),
                    }

            stdout_b, stderr_rest = await proc.communicate()
            if stdout_b:
                combined_stdout.append(stdout_b.decode(errors="replace"))
            if stderr_rest:
                combined_stderr.append(stderr_rest.decode(errors="replace"))

            if proc.returncode != 0:
                raise RuntimeError(
                    f"rsync exit {proc.returncode}: "
                    + "".join(combined_stderr)[-2000:]
                )

        for step in sync_plan:
            if step["type"] == "synology_smb":
                share, subpath, desc = describe_synology_pull(step["src_path"])
                logger.info("FileReplicationJob %s pull Synology SMB %s", job_id, desc)
                out, err = await pull_synology_share(
                    source, share, subpath, step["local_dir"]
                )
                combined_stdout.extend(out)
                combined_stderr.extend(err)
            elif step["type"] == "rsync":
                await _run_rsync(step["cmd"])

        duration = int((datetime.utcnow() - started).total_seconds())
        job.last_run_at = datetime.utcnow()
        job.last_run_status = "success"
        job.last_run_duration_sec = duration
        job.last_bytes_transferred = total_bytes
        job.current_status = "idle"
        db.commit()

        if log_row:
            log_row.status = "success"
            log_row.message = f"Replica completata in {duration}s"
            log_row.output = "".join(combined_stdout)[-50000:]
            db.commit()

        _progress[job_id] = {"status": "success", "bytes_transferred": total_bytes}

        if job.notify_mode in ("always", "daily"):
            try:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="success",
                    source=source.name,
                    destination=dest.name,
                    duration=duration,
                    transferred=str(total_bytes),
                    job_type="file_replication",
                    notify_mode=job.notify_mode,
                )
            except Exception as notify_err:
                logger.warning("Notifica file replication fallita: %s", notify_err)

    except Exception as exc:
        logger.error("FileReplicationJob %s fallito: %s", job_id, exc, exc_info=True)
        duration = int((datetime.utcnow() - started).total_seconds())
        err_text = str(exc)
        job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
        if job:
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "failed"
            job.last_run_duration_sec = duration
            job.current_status = "failed"
        _write_failure_log(
            db,
            job_id=job_id,
            log_row=log_row,
            job=job,
            dest=dest,
            error=err_text,
            duration=duration,
        )
        db.commit()
        _progress[job_id] = {"status": "failed", "error": err_text}
        if job and job.notify_mode in ("always", "failure", "daily"):
            try:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="failed",
                    source=source.name if source else "?",
                    destination=dest.name if dest else "?",
                    duration=duration,
                    error=str(exc),
                    job_type="file_replication",
                    notify_mode=job.notify_mode,
                )
            except Exception as notify_err:
                logger.warning("Notifica failure fallita: %s", notify_err)
    finally:
        if exclude_path and os.path.exists(exclude_path):
            try:
                os.unlink(exclude_path)
            except OSError:
                pass
        if staging_dir and os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        _running.discard(job_id)
        db.close()
