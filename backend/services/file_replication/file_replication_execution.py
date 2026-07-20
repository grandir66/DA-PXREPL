"""Esecuzione job replica file."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime
from typing import Optional

from database import FileEndpoint, FileEndpointType, FileReplicationJob, JobLog, SessionLocal
from services.file_replication.endpoint_crypto import decrypt_password
from services.file_replication.exclude_presets import (
    build_rclone_filter_lines,
    build_rsync_exclude_lines,
)
from services.file_replication.file_replication_state import (
    apply_resume_to_sync_plan,
    assign_run_state,
    catalog_to_progress_fields,
    clear_resume,
    compose_live_progress,
    expand_rclone_steps_by_catalog,
    folder_progress_to_fields,
    get_run_state,
    has_du_catalog,
    mark_all_folders_done,
    mark_folder_step_complete,
    mark_folder_step_started,
    reset_folder_run_progress,
    save_pause_checkpoint,
    strip_ui_progress,
    update_catalog_from_progress,
    update_folder_work_progress,
)
from services.file_replication.file_sync_service import build_sync_plan, parse_rsync_progress
from services.file_replication.file_replication_notifications import notify_file_replication_result
from services.file_replication.file_replication_report import (
    build_file_replication_report,
    report_transferred_human,
)
from services.file_replication.path_utils import parse_synology_share_path, sanitize_path
from services.file_replication.rclone_sync import (
    RcloneCancelledError,
    enrich_rclone_progress_view,
    format_rclone_progress_summary,
    merge_rclone_progress,
    parse_rclone_progress,
    preflight_rclone,
    rclone_sync_synology_to_qnap,
    summarize_rclone_output,
)
from services.size_utils import parse_transfer_size_to_bytes

logger = logging.getLogger(__name__)

_running: set[int] = set()
_cancel_requested: set[int] = set()
_processes: dict[int, list[asyncio.subprocess.Process]] = {}
_progress: dict[int, dict] = {}
_last_state_persist: dict[int, float] = {}
_STATE_PERSIST_INTERVAL = 15.0


class JobCancelledError(Exception):
    """Job replica file annullato dall'utente."""


def _job_pid_file(job_id: int) -> str:
    return f"/tmp/dapx-fr-job-{job_id}.pid"


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pid_file(job_id: int) -> bool:
    path = _job_pid_file(job_id)
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            pid = int(fh.read().strip())
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    try:
        os.unlink(path)
    except OSError:
        pass
    return True


def _kill_orphan_rclone(job: FileReplicationJob) -> int:
    """Termina processi rclone avviati da run precedenti (senza pid file)."""
    killed = 0
    seen_pids: set[int] = set()
    for src_path in job.source_paths or []:
        try:
            share, _sub = parse_synology_share_path(src_path)
        except ValueError:
            continue
        needle = f"fr_source:{share}"
        try:
            proc = subprocess.run(
                ["pgrep", "-f", needle],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        for pid_s in proc.stdout.split():
            try:
                pid = int(pid_s)
            except ValueError:
                continue
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            try:
                os.killpg(pid, signal.SIGTERM)
                killed += 1
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                except OSError:
                    pass
    return killed


def reconcile_stale_running_jobs() -> int:
    """All'avvio: job ``running`` in DB senza processo vivo → idle."""
    db = SessionLocal()
    reset = 0
    try:
        jobs = (
            db.query(FileReplicationJob)
            .filter(FileReplicationJob.current_status == "running")
            .all()
        )
        for job in jobs:
            if job.id in _running:
                continue
            pid_path = _job_pid_file(job.id)
            alive = False
            if os.path.isfile(pid_path):
                try:
                    with open(pid_path, encoding="utf-8") as fh:
                        alive = _process_alive(int(fh.read().strip()))
                except (OSError, ValueError):
                    alive = False
            if not alive:
                job.current_status = "idle"
                reset += 1
        if reset:
            db.commit()
    finally:
        db.close()
    return reset


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


def is_job_busy(job_id: int) -> bool:
    from services.file_replication.file_replication_du_catalog import is_catalog_refresh_running

    return job_id in _running or is_catalog_refresh_running(job_id)


def get_job_progress(job_id: int) -> Optional[dict]:
    return _progress.get(job_id)


def _maybe_persist_run_state(
    db,
    job_id: int,
    job: FileReplicationJob,
    state: dict,
    *,
    force: bool = False,
) -> None:
    now = time.monotonic()
    if not force and now - _last_state_persist.get(job_id, 0) < _STATE_PERSIST_INTERVAL:
        return
    assign_run_state(job, state)
    db.commit()
    _last_state_persist[job_id] = now


def _merge_catalog_into_progress(
    job_id: int,
    run_state: dict,
    *,
    source_root: str = "",
    step_path: str = "",
    last_file: str | None = None,
) -> None:
    if job_id not in _progress:
        return
    fields = catalog_to_progress_fields(run_state)
    if source_root:
        fields.update(
            folder_progress_to_fields(
                run_state,
                source_root,
                step_path=step_path or source_root,
                last_file=last_file,
            )
        )
    if fields:
        _progress[job_id] = compose_live_progress(_progress[job_id], fields)


async def _apply_cached_catalog_to_progress(
    job_id: int,
    job: FileReplicationJob,
    run_state: dict,
) -> None:
    """Carica il catalogo du persistito in ``run_state`` (nessuna scansione du)."""
    paths = [sanitize_path(p) for p in (job.source_paths or []) if p]
    fields = catalog_to_progress_fields(run_state)
    for src_path in paths:
        fields.update(
            folder_progress_to_fields(run_state, src_path, step_path=src_path)
        )
    if fields:
        _progress[job_id] = compose_live_progress(_progress.get(job_id, {}), fields)
    if paths and not has_du_catalog(run_state, paths):
        hint = (
            "Catalogo du non presente: esegui «Aggiorna catalogo» per dimensioni "
            "e avanzamento per cartella."
        )
        _progress[job_id] = compose_live_progress(
            _progress.get(job_id, {}),
            {"catalog_missing": True, "hint": hint},
        )
        logger.warning("FileReplicationJob %s avviato senza catalogo du persistito", job_id)


async def stop_file_replication_job(job_id: int) -> dict:
    """Interrompe un job in esecuzione (processo rclone/rsync e eventuale orphan)."""
    _cancel_requested.add(job_id)
    killed = False
    for proc in _processes.get(job_id, []):
        if proc.returncode is None and proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                killed = True
            except ProcessLookupError:
                proc.terminate()
                killed = True
    if _kill_pid_file(job_id):
        killed = True

    db = SessionLocal()
    try:
        job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
        if not job:
            raise ValueError("Job non trovato")
        if _kill_orphan_rclone(job):
            killed = True
        if killed or job_id in _running:
            if job_id not in _running and job.current_status == "running":
                job.current_status = "paused"
                job.last_run_status = "paused"
            db.commit()
            _progress[job_id] = {
                **_progress.get(job_id, {}),
                "status": "cancelling",
                "message": "Interruzione in corso…",
            }
            return {"ok": True, "message": "Interruzione richiesta"}
        return {"ok": False, "message": "Job non in esecuzione"}
    finally:
        db.close()


async def execute_file_replication_job(job_id: int, *, fresh: bool = False) -> None:
    if job_id in _running:
        logger.warning("FileReplicationJob %s già in esecuzione", job_id)
        return

    _running.add(job_id)
    _cancel_requested.discard(job_id)
    _processes[job_id] = []
    pid_file = _job_pid_file(job_id)
    _progress[job_id] = enrich_rclone_progress_view({
        "status": "running",
        "phase": "starting",
        "transferred_human": "0 B",
        "files_copied": 0,
        "files_skipped": 0,
        "files_done": 0,
    })
    db = SessionLocal()
    log_row: Optional[JobLog] = None
    started = datetime.utcnow()
    exclude_path: Optional[str] = None
    filter_path: Optional[str] = None
    staging_dir: Optional[str] = None
    source: Optional[FileEndpoint] = None
    dest: Optional[FileEndpoint] = None
    current_plan_index = 0
    current_source_path = ""
    last_file_seen: Optional[str] = None
    run_state: dict = {}

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
        if (
            source.endpoint_type == FileEndpointType.SYNOLOGY
            and dest.endpoint_type == FileEndpointType.QNAP
        ):
            preflight_rclone()

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

        exclude_lines = build_rsync_exclude_lines(
            job.exclude_presets or [], job.exclude_patterns or []
        )
        filter_lines = build_rclone_filter_lines(
            job.exclude_presets or [], job.exclude_patterns or []
        )
        fd, exclude_path = tempfile.mkstemp(prefix="dapx-fr-exclude-", suffix=".txt")
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(exclude_lines) + "\n")

        fd2, filter_path = tempfile.mkstemp(prefix="dapx-fr-rclone-filter-", suffix=".txt")
        with os.fdopen(fd2, "w") as fh:
            fh.write("\n".join(filter_lines) + "\n")

        staging_dir = tempfile.mkdtemp(prefix=f"dapx-fr-{job_id}-")
        full_sync_plan = build_sync_plan(
            job,
            source,
            dest,
            exclude_path,
            staging_dir,
            filter_file=filter_path,
        )
        run_state = get_run_state(job)
        if fresh:
            run_state = clear_resume(run_state)
            run_state = reset_folder_run_progress(run_state)
            assign_run_state(job, run_state)
            db.commit()
        expanded_plan, folders_skipped = expand_rclone_steps_by_catalog(
            full_sync_plan,
            run_state,
            job.dest_staging_path,
        )
        sync_plan, resume_note = apply_resume_to_sync_plan(
            expanded_plan,
            run_state,
            job.dest_staging_path,
        )
        skip_parts: list[str] = []
        if folders_skipped:
            skip_parts.append(f"{folders_skipped} cartelle già allineate saltate")
        if resume_note:
            skip_parts.insert(0, resume_note)
        if skip_parts:
            _progress[job_id] = compose_live_progress(
                _progress.get(job_id, {}),
                {
                    **catalog_to_progress_fields(run_state),
                    "hint": " — ".join(skip_parts),
                },
                status="running",
                message=skip_parts[0],
            )
        await _apply_cached_catalog_to_progress(job_id, job, run_state)
        combined_stdout: list[str] = []
        combined_stderr: list[str] = []
        total_bytes = 0

        async def _run_rsync(cmd: list[str]) -> None:
            nonlocal total_bytes
            if job_id in _cancel_requested:
                raise JobCancelledError("Interrotto dall'utente")
            logger.info("FileReplicationJob %s rsync: %s", job_id, " ".join(cmd[:8]))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
            except FileNotFoundError as exc:
                missing = cmd[0] if cmd else "rsync"
                raise RuntimeError(
                    f"'{missing}' non trovato sul server dapx. "
                    "Installare con: apt install rsync openssh-client sshpass cifs-utils"
                ) from exc
            _processes[job_id].append(proc)
            assert proc.stderr is not None
            while proc.returncode is None:
                if job_id in _cancel_requested:
                    if proc.pid:
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            proc.terminate()
                    raise JobCancelledError("Interrotto dall'utente")
                try:
                    line_b = await asyncio.wait_for(proc.stderr.readline(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
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
            current_plan_index = int(step.get("plan_index", current_plan_index))
            current_source_path = step.get("original_src_path") or step.get("src_path") or ""
            if step["type"] == "rclone_sync":
                catalog_root = sanitize_path(
                    step.get("original_src_path")
                    or step.get("src_path")
                    or current_source_path
                )
                folder_path = step.get("catalog_folder_path")
                step_msg = f"rclone {step['src_path']}"
                if folder_path:
                    name = step["src_path"].split("/")[-1]
                    step_msg = f"rclone cartella {name}"
                if step.get("resumed_from"):
                    step_msg = f"{step_msg} (ripresa)"
                rclone_state: dict = strip_ui_progress(dict(_progress.get(job_id) or {}))
                current_source_path = catalog_root
                step_src = step["src_path"]
                if folder_path:
                    run_state = mark_folder_step_started(
                        run_state,
                        catalog_root,
                        str(folder_path),
                    )
                    _maybe_persist_run_state(db, job_id, job, run_state)
                else:
                    run_state, _ = update_folder_work_progress(
                        run_state,
                        catalog_root,
                        step_path=step_src,
                        last_file=None,
                        progress=rclone_state,
                    )

                def _on_rclone_line(
                    line: str,
                    _msg: str = step_msg,
                    _step_src: str = step_src,
                    _catalog_root: str = catalog_root,
                ) -> None:
                    patch = parse_rclone_progress(line)
                    if not patch:
                        return
                    nonlocal rclone_state, last_file_seen, run_state
                    rclone_state = merge_rclone_progress(rclone_state, patch)
                    if patch.get("last_file"):
                        last_file_seen = patch["last_file"]
                    if patch.get("last_file"):
                        file_event = None
                        if patch.get("files_copied_delta"):
                            file_event = "copied"
                        elif patch.get("files_skipped_delta"):
                            file_event = "skipped"
                        elif patch.get("files_deleted_delta"):
                            file_event = "deleted"
                        run_state = update_catalog_from_progress(
                            run_state,
                            rclone_state,
                            _catalog_root,
                        )
                        run_state, _ = update_folder_work_progress(
                            run_state,
                            _catalog_root,
                            step_path=_step_src,
                            last_file=rclone_state.get("last_file"),
                            progress=rclone_state,
                            file_event=file_event,
                        )
                    else:
                        run_state = update_catalog_from_progress(
                            run_state,
                            rclone_state,
                            _catalog_root,
                        )
                    _maybe_persist_run_state(db, job_id, job, run_state)
                    folder_fields = folder_progress_to_fields(
                        run_state,
                        _catalog_root,
                        step_path=_step_src,
                        last_file=rclone_state.get("last_file"),
                    )
                    _progress[job_id] = compose_live_progress(
                        rclone_state,
                        {**catalog_to_progress_fields(run_state), **folder_fields},
                        status="running",
                        message=_msg,
                    )

                out, err = await rclone_sync_synology_to_qnap(
                    source,
                    dest,
                    step["src_path"],
                    step["dest_dir"],
                    delete_on_dest=bool(step.get("delete_on_dest")),
                    filter_file=step.get("filter_file"),
                    bandwidth_limit_kb=step.get("bandwidth_limit_kb"),
                    size_only=bool(step.get("size_only")),
                    on_line=_on_rclone_line,
                    cancel_check=lambda: job_id in _cancel_requested,
                    process_registry=_processes[job_id],
                    pid_file=pid_file,
                )
                combined_stdout.extend(out)
                combined_stderr.extend(err)
                if folder_path:
                    run_state = mark_folder_step_complete(
                        run_state,
                        catalog_root,
                        str(folder_path),
                    )
                else:
                    run_state = mark_all_folders_done(run_state, catalog_root)
                _maybe_persist_run_state(db, job_id, job, run_state, force=True)
                step_summary = summarize_rclone_output(out)
                if step_summary:
                    rclone_state = merge_rclone_progress(rclone_state, step_summary)
                    run_state = update_catalog_from_progress(
                        run_state,
                        rclone_state,
                        current_source_path,
                    )
                    _maybe_persist_run_state(db, job_id, job, run_state, force=True)
                    folder_fields = folder_progress_to_fields(
                        run_state,
                        catalog_root,
                        step_path=step_src,
                        last_file=rclone_state.get("last_file"),
                    )
                    _progress[job_id] = compose_live_progress(
                        rclone_state,
                        {**catalog_to_progress_fields(run_state), **folder_fields},
                        status="running",
                        message=step_msg,
                    )
            elif step["type"] == "rsync":
                await _run_rsync(step["cmd"])

        duration = int((datetime.utcnow() - started).total_seconds())
        final_progress = dict(_progress.get(job_id) or {})
        progress_summary = format_rclone_progress_summary(final_progress)
        if not total_bytes and final_progress.get("transferred_human"):
            total_bytes = parse_transfer_size_to_bytes(final_progress["transferred_human"])
        transferred_label = report_transferred_human(final_progress, total_bytes)
        files_copied = int(final_progress.get("files_copied") or final_progress.get("files_done") or 0)
        report_text = build_file_replication_report(
            job=job,
            source=source,
            dest=dest,
            duration_sec=duration,
            progress={**final_progress, "summary": progress_summary},
            total_bytes=total_bytes,
        )

        if current_source_path:
            run_state = update_catalog_from_progress(
                run_state,
                final_progress,
                current_source_path,
            )
        run_state = clear_resume(run_state)
        assign_run_state(job, run_state)

        job.last_run_at = datetime.utcnow()
        job.last_run_status = "success"
        job.last_run_duration_sec = duration
        job.last_bytes_transferred = total_bytes
        job.last_files_transferred = files_copied
        job.current_status = "idle"
        db.commit()

        if log_row:
            log_row.status = "success"
            log_row.message = report_text.split("\n")[0] if report_text else f"Replica completata in {duration}s"
            if progress_summary:
                log_row.message = f"Replica completata in {duration}s — {progress_summary}"
            log_row.output = report_text + "\n\n--- rclone/rsync ---\n" + "".join(combined_stdout)[-45000:]
            log_row.duration = duration
            log_row.transferred = transferred_label
            log_row.completed_at = datetime.utcnow()
            db.commit()

        _progress[job_id] = {
            **final_progress,
            "status": "success",
            "summary": progress_summary,
            "report": report_text,
        }

        await notify_file_replication_result(
            job=job,
            source=source,
            dest=dest,
            status="success",
            duration=duration,
            progress=final_progress,
            total_bytes=total_bytes,
            is_scheduled=bool(job.schedule),
        )

    except (JobCancelledError, RcloneCancelledError):
        logger.info("FileReplicationJob %s interrotto dall'utente", job_id)
        duration = int((datetime.utcnow() - started).total_seconds())
        job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
        if job:
            pause_progress = dict(_progress.get(job_id) or {})
            run_state = get_run_state(job)
            run_state = save_pause_checkpoint(
                run_state,
                step_index=current_plan_index,
                source_path=current_source_path or (job.source_paths or [""])[0],
                last_file=last_file_seen or pause_progress.get("last_file"),
                progress=pause_progress,
            )
            assign_run_state(job, run_state)
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "paused"
            job.last_run_duration_sec = duration
            job.current_status = "paused"
            catalog_root = current_source_path or (job.source_paths or [""])[0]
            folder_fields = folder_progress_to_fields(
                run_state,
                catalog_root,
                step_path=current_source_path or catalog_root,
                last_file=last_file_seen or pause_progress.get("last_file"),
            )
        else:
            folder_fields = {}
        if log_row:
            log_row.status = "cancelled"
            log_row.message = "Replica messa in pausa dall'utente"
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
        db.commit()
        _progress[job_id] = compose_live_progress(
            _progress.get(job_id, {}),
            folder_fields,
            status="paused",
            message="In pausa — riprendi dal checkpoint salvato",
        )
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
        if log_row and job and source and dest:
            log_row.output = err_text
        db.commit()
        _progress[job_id] = {"status": "failed", "error": err_text}
        if job and source and dest:
            await notify_file_replication_result(
                job=job,
                source=source,
                dest=dest,
                status="failed",
                duration=duration,
                error=err_text,
                is_scheduled=bool(job.schedule),
            )
    finally:
        _cancel_requested.discard(job_id)
        _processes.pop(job_id, None)
        _last_state_persist.pop(job_id, None)
        if os.path.isfile(pid_file):
            try:
                os.unlink(pid_file)
            except OSError:
                pass
        if exclude_path and os.path.exists(exclude_path):
            try:
                os.unlink(exclude_path)
            except OSError:
                pass
        if filter_path and os.path.exists(filter_path):
            try:
                os.unlink(filter_path)
            except OSError:
                pass
        if staging_dir and os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        _running.discard(job_id)
        db.close()
