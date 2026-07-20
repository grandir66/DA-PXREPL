"""Orchestratore esecuzione job Repliche dati: engine-agnostico, stato, pausa, log."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from database import FileEndpoint, JobLog, SessionLocal
from services.file_replication.exclude_presets import (
    build_rclone_filter_lines,
    build_rsync_exclude_lines,
)
from services.file_replication.path_utils import sanitize_path
from services.nas_sync.capabilities import ENGINE_DIRECT, resolve_engine
from services.nas_sync.du_catalog import is_catalog_refresh_running
from services.nas_sync.engine_direct_rsync import (
    EngineCancelled,
    EngineError,
    StepResult,
    kill_remote_rsync,
    run_direct_rsync,
)
from services.nas_sync.engine_rclone import run_rclone_step
from services.nas_sync.events import SyncEvent, apply_event, build_view
from services.nas_sync.models import NasSyncJob
from services.nas_sync.notifications import notify_nas_sync_result
from services.nas_sync.state import (
    assign_run_state,
    catalog_summary,
    clear_pause,
    get_pause,
    get_run_state,
    mark_folder_done,
    pending_folders,
    reset_run_progress,
    save_pause,
)

logger = logging.getLogger(__name__)

_running: set[int] = set()
_cancel_requested: set[int] = set()
_processes: dict[int, list] = {}
_remote_pids: dict[int, tuple[int, int]] = {}  # job_id -> (source_endpoint_id, pid)
_progress: dict[int, dict] = {}


def is_job_running(job_id: int) -> bool:
    return job_id in _running


def is_job_busy(job_id: int) -> bool:
    return job_id in _running or is_catalog_refresh_running(job_id)


def get_job_progress(job_id: int) -> Optional[dict]:
    return _progress.get(job_id)


def reconcile_stale_running_jobs() -> int:
    """All'avvio backend: job 'running' in DB senza run in memoria → paused."""
    db = SessionLocal()
    reset = 0
    try:
        jobs = db.query(NasSyncJob).filter(NasSyncJob.current_status == "running").all()
        for job in jobs:
            if job.id not in _running:
                job.current_status = "paused"
                job.last_run_status = "paused"
                reset += 1
        if reset:
            db.commit()
    finally:
        db.close()
    return reset


async def stop_nas_sync_job(job_id: int) -> dict:
    if job_id not in _running:
        return {"ok": False, "message": "Job non in esecuzione"}
    _cancel_requested.add(job_id)
    remote = _remote_pids.get(job_id)
    if remote:
        db = SessionLocal()
        try:
            source = db.query(FileEndpoint).filter(FileEndpoint.id == remote[0]).first()
            if source:
                await kill_remote_rsync(source, remote[1])
        finally:
            db.close()
    _progress[job_id] = {
        **(_progress.get(job_id) or {}),
        "status": "cancelling",
        "message": "Interruzione in corso…",
    }
    return {"ok": True, "message": "Interruzione richiesta"}


def _build_steps(job: NasSyncJob, run_state: dict) -> list[dict]:
    """Step di lavoro: per-cartella se il catalogo du esiste, altrimenti per source_path."""
    steps: list[dict] = []
    pause = get_pause(run_state)
    for src_path in job.source_paths or []:
        root = sanitize_path(src_path)
        folders = pending_folders(run_state, root)
        if folders:
            for folder in folders:
                steps.append({"src_path": folder["path"], "root": root,
                              "folder_path": folder["path"]})
        else:
            catalog_present = bool((run_state.get("catalog") or {}).get(root))
            done_all = catalog_present and not folders
            if done_all and not pause:
                continue  # tutte le cartelle già replicate in run precedente
            steps.append({"src_path": root, "root": root, "folder_path": None})
    if not steps and (job.source_paths or []):
        # catalogo completo ma nessun pending (es. resume completato): replica root per sicurezza delete
        for src_path in job.source_paths or []:
            root = sanitize_path(src_path)
            steps.append({"src_path": root, "root": root, "folder_path": None})
    return steps


async def _run_engine_step(
    engine: str,
    job: NasSyncJob,
    source: FileEndpoint,
    dest: FileEndpoint,
    step: dict,
    exclude_lines: list[str],
    filter_file: str | None,
    on_event,
    job_id: int,
) -> StepResult:
    if engine == ENGINE_DIRECT:
        result = await run_direct_rsync(
            source,
            dest,
            step["src_path"],
            (job.dest_base_path or "").strip(),
            exclude_lines=exclude_lines,
            delete_on_dest=bool(job.delete_on_dest),
            bandwidth_limit_kb=job.bandwidth_limit_kb,
            on_event=on_event,
            cancel_check=lambda: job_id in _cancel_requested,
            process_registry=_processes[job_id],
        )
        if result.remote_pid:
            _remote_pids[job_id] = (source.id, result.remote_pid)
        return result
    return await run_rclone_step(
        source,
        dest,
        step["src_path"],
        job.dest_base_path or "",
        delete_on_dest=bool(job.delete_on_dest),
        size_only=bool(job.rclone_size_only),
        bandwidth_limit_kb=job.bandwidth_limit_kb,
        filter_file=filter_file,
        on_event=on_event,
        cancel_check=lambda: job_id in _cancel_requested,
        process_registry=_processes[job_id],
    )


async def execute_nas_sync_job(job_id: int, *, fresh: bool = False, _engine_runner=None) -> None:
    if job_id in _running:
        logger.warning("NasSyncJob %s già in esecuzione", job_id)
        return
    _running.add(job_id)
    _cancel_requested.discard(job_id)
    _processes[job_id] = []
    _progress[job_id] = build_view({"status": "running", "phase": "starting"})
    started = datetime.utcnow()
    db = SessionLocal()
    log_row: Optional[JobLog] = None
    source: Optional[FileEndpoint] = None
    dest: Optional[FileEndpoint] = None
    current_step: dict = {}
    progress_state: dict = {}
    warnings: list[str] = []
    output_tail: list[str] = []
    filter_path: Optional[str] = None

    try:
        job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
        if not job:
            logger.error("NasSyncJob %s non trovato", job_id)
            return
        source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
        dest = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()
        if not source or not dest:
            raise RuntimeError("Endpoint sorgente o destinazione mancante")

        engine, reason = resolve_engine(job.sync_method or "auto", source, dest)
        job.resolved_engine = engine
        job.current_status = "running"
        db.commit()

        log_row = JobLog(
            job_type="nas_sync",
            job_id=job.id,
            node_name=dest.name,
            dataset=job.dest_base_path,
            status="started",
            message=f"Avvio replica dati: {job.name} [{engine}]",
        )
        db.add(log_row)
        db.commit()

        exclude_lines = build_rsync_exclude_lines(
            job.exclude_presets or [], job.exclude_patterns or []
        )
        if engine != ENGINE_DIRECT:
            import os
            import tempfile

            filter_lines = build_rclone_filter_lines(
                job.exclude_presets or [], job.exclude_patterns or []
            )
            fd, filter_path = tempfile.mkstemp(prefix="dapx-nas2-filter-", suffix=".txt")
            with os.fdopen(fd, "w") as fh:
                fh.write("\n".join(filter_lines) + "\n")

        run_state = get_run_state(job)
        if fresh:
            run_state = reset_run_progress(run_state)
            assign_run_state(job, run_state)
            db.commit()
        run_state = clear_pause(run_state)

        def on_event(ev: SyncEvent) -> None:
            nonlocal progress_state
            progress_state = apply_event(progress_state, ev)
            view = build_view(progress_state)
            view["status"] = "running"
            view.update(catalog_summary(run_state))
            if current_step.get("folder_path"):
                view["current_folder_path"] = current_step["folder_path"]
                view["current_folder_name"] = current_step["folder_path"].rsplit("/", 1)[-1]
            _progress[job_id] = view

        steps = _build_steps(job, run_state)
        for step in steps:
            current_step.clear()
            current_step.update(step)
            if job_id in _cancel_requested:
                raise EngineCancelled("Interrotto dall'utente")
            if _engine_runner is not None:
                result = await _engine_runner(
                    {"engine": engine, "src_path": step["src_path"],
                     "folder_path": step["folder_path"],
                     "dest_subpath": job.dest_base_path or ""}
                )
            else:
                result = await _run_engine_step(
                    engine, job, source, dest, step, exclude_lines, filter_path,
                    on_event, job_id,
                )
            warnings.extend(result.warnings)
            output_tail.extend(result.output_lines[-200:])
            if step["folder_path"]:
                run_state = mark_folder_done(run_state, step["root"], step["folder_path"])
                assign_run_state(job, run_state)
                db.commit()

        duration = int((datetime.utcnow() - started).total_seconds())
        final_view = build_view(progress_state)
        job.last_run_at = datetime.utcnow()
        job.last_run_status = "success"
        job.last_run_duration_sec = duration
        job.last_bytes_transferred = int(progress_state.get("bytes_done") or 0)
        job.last_files_transferred = int(progress_state.get("files_copied") or 0)
        job.current_status = "idle"
        run_state = reset_run_progress(run_state)
        assign_run_state(job, run_state)
        db.commit()

        if log_row:
            summary = final_view.get("display_summary") or f"Replica completata in {duration}s"
            if warnings:
                summary += " — con avvisi"
            log_row.status = "success"
            log_row.message = summary
            log_row.output = ("\n".join(warnings) + "\n\n" if warnings else "") + "".join(output_tail)[-45000:]
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
            db.commit()

        _progress[job_id] = {**final_view, "status": "success", "warnings": warnings}
        await notify_nas_sync_result(
            job, source, dest, status="success", duration=duration,
            progress=final_view, is_scheduled=bool(job.schedule),
        )

    except EngineCancelled:
        duration = int((datetime.utcnow() - started).total_seconds())
        job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
        if job:
            run_state = get_run_state(job)
            run_state = save_pause(
                run_state,
                current_step.get("root") or (job.source_paths or [""])[0],
                current_step.get("folder_path"),
                progress_state.get("last_file"),
            )
            assign_run_state(job, run_state)
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "paused"
            job.last_run_duration_sec = duration
            job.current_status = "paused"
        if log_row:
            log_row.status = "cancelled"
            log_row.message = "Replica messa in pausa dall'utente"
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
        db.commit()
        _progress[job_id] = {
            **build_view(progress_state),
            "status": "paused",
            "message": "In pausa — riprendi dal checkpoint salvato",
        }
    except Exception as exc:  # noqa: BLE001 — qualunque errore chiude il run come failed
        logger.error("NasSyncJob %s fallito: %s", job_id, exc, exc_info=True)
        duration = int((datetime.utcnow() - started).total_seconds())
        err_text = str(exc)
        job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
        if job:
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "failed"
            job.last_run_duration_sec = duration
            job.current_status = "failed"
        if log_row:
            log_row.status = "failed"
            log_row.error = err_text
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
        elif job:
            db.add(JobLog(
                job_type="nas_sync", job_id=job_id,
                node_name=dest.name if dest else None,
                dataset=job.dest_base_path, status="failed",
                message=f"Replica fallita: {job.name}", error=err_text,
                duration=duration, completed_at=datetime.utcnow(),
            ))
        db.commit()
        _progress[job_id] = {"status": "failed", "error": err_text}
        if job and source and dest:
            await notify_nas_sync_result(
                job, source, dest, status="failed", duration=duration,
                error=err_text, is_scheduled=bool(job.schedule),
            )
    finally:
        import os as _os

        _cancel_requested.discard(job_id)
        _processes.pop(job_id, None)
        _remote_pids.pop(job_id, None)
        if filter_path:
            try:
                _os.unlink(filter_path)
            except OSError:
                pass
        _running.discard(job_id)
        db.close()
