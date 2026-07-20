"""Catalogo dimensioni per-cartella (du -sb via SSH sulla sorgente) — job separato dalla replica."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from database import FileEndpoint, SessionLocal
from services.file_replication.path_utils import sanitize_path
from services.nas_sync.engine_direct_rsync import build_source_fs_path, build_ssh_argv
from services.nas_sync.models import NasSyncJob
from services.nas_sync.state import assign_run_state, folder_progress_fields, get_run_state, set_du_catalog


logger = logging.getLogger(__name__)

_catalog_running: set[int] = set()
_catalog_progress: dict[int, dict] = {}


def is_catalog_refresh_running(job_id: int) -> bool:
    return job_id in _catalog_running


def get_catalog_progress(job_id: int) -> dict | None:
    return _catalog_progress.get(job_id)


def build_du_script(fs_root: str) -> str:
    root = fs_root.rstrip("/")
    return (
        f"du -sb '{root}' 2>/dev/null; "
        f"find '{root}' -mindepth 1 -maxdepth 1 -type d "
        "! -name '@*' ! -name '#*' ! -name '.*' -print0 2>/dev/null "
        "| xargs -0 -r -n1 du -sb 2>/dev/null"
    )


def parse_du_output(text: str, fs_root: str, src_root: str) -> tuple[list[dict], int]:
    root = fs_root.rstrip("/")
    logical_root = sanitize_path(src_root).rstrip("/")
    folders: list[dict] = []
    total = 0
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        try:
            size = int(parts[0].strip())
        except ValueError:
            continue
        path = parts[1].strip().rstrip("/")
        if path == root:
            total = size
            continue
        if not path.startswith(root + "/"):
            continue
        rel = path[len(root) + 1 :]
        if "/" in rel:
            continue  # solo primo livello
        folders.append({"path": f"{logical_root}/{rel}", "name": rel, "bytes": size})
    return folders, total


async def refresh_job_du_catalog(job_id: int) -> None:
    if job_id in _catalog_running:
        return
    _catalog_running.add(job_id)
    _catalog_progress[job_id] = {
        "status": "catalog_refresh",
        "phase": "starting",
        "phase_label": "Catalogo du sorgente",
        "message": "Catalogo du in corso…",
    }
    db = SessionLocal()
    try:
        job = db.query(NasSyncJob).filter(NasSyncJob.id == job_id).first()
        if not job:
            return
        source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
        if not source:
            _catalog_progress[job_id] = {"status": "failed", "error": "Endpoint sorgente mancante"}
            return
        state = get_run_state(job)
        argv, env = build_ssh_argv(source)
        for src_path in job.source_paths or []:
            fs_root = build_source_fs_path(source, src_path)
            script = build_du_script(fs_root)
            _catalog_progress[job_id] = {
                "status": "catalog_refresh",
                "phase": "starting",
                "phase_label": "Catalogo du sorgente",
                "message": f"du {src_path}…",
                **folder_progress_fields(state),
            }
            proc = await asyncio.create_subprocess_exec(
                *argv,
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ, **env},
            )
            out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=3600)
            folders, total = parse_du_output(
                out_b.decode(errors="replace"), fs_root, src_path
            )
            state = set_du_catalog(
                state, sanitize_path(src_path), folders, total, None,
                datetime.utcnow().isoformat(timespec="seconds"),
            )
            _catalog_progress[job_id] = {
                "status": "catalog_refresh",
                "phase": "starting",
                "phase_label": "Catalogo du sorgente",
                "message": f"Catalogo aggiornato: {src_path} ({len(folders)} cartelle)",
                **folder_progress_fields(state),
            }
        assign_run_state(job, state)
        db.commit()
        _catalog_progress[job_id] = {
            "status": "success",
            "phase": "done",
            "phase_label": "Catalogo du completato",
            "message": "Catalogo du aggiornato",
            **folder_progress_fields(state),
        }
    except Exception as exc:  # noqa: BLE001 — task fire-and-forget, errore in progress
        logger.error("nas_sync du catalog %s fallito: %s", job_id, exc, exc_info=True)
        _catalog_progress[job_id] = {"status": "failed", "error": str(exc)}
    finally:
        _catalog_running.discard(job_id)
        db.close()
