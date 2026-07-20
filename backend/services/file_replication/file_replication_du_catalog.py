"""Aggiornamento catalogo du Synology (job separato dalla replica)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from database import FileEndpoint, FileEndpointType, FileReplicationJob, JobLog, SessionLocal
from services.file_replication.file_replication_state import (
    assign_run_state,
    catalog_to_progress_fields,
    folder_progress_to_fields,
    get_run_state,
    update_catalog_from_du_folders,
)
from services.file_replication.path_utils import sanitize_path
from services.file_replication.rclone_sync import enrich_rclone_progress_view
from services.file_replication.synology_du import synology_du_folder_catalog

logger = logging.getLogger(__name__)

_catalog_running: set[int] = set()
_catalog_progress: dict[int, dict] = {}


class CatalogCancelledError(Exception):
    """Aggiornamento catalogo interrotto."""


_catalog_cancel_requested: set[int] = set()


def is_catalog_refresh_running(job_id: int) -> bool:
    return job_id in _catalog_running


def get_catalog_progress(job_id: int) -> Optional[dict]:
    return _catalog_progress.get(job_id)


def request_catalog_cancel(job_id: int) -> None:
    _catalog_cancel_requested.add(job_id)


async def refresh_job_du_catalog(job_id: int) -> None:
    """Scansiona du 1° livello su Synology e persiste in ``run_state``."""
    if job_id in _catalog_running:
        logger.warning("Catalog refresh job %s già in esecuzione", job_id)
        return

    _catalog_running.add(job_id)
    _catalog_cancel_requested.discard(job_id)
    started = datetime.utcnow()
    db = SessionLocal()
    log_row: Optional[JobLog] = None

    try:
        job = db.query(FileReplicationJob).filter(FileReplicationJob.id == job_id).first()
        if not job:
            logger.error("FileReplicationJob %s non trovato per catalog refresh", job_id)
            return

        source = (
            db.query(FileEndpoint)
            .filter(FileEndpoint.id == job.source_endpoint_id)
            .first()
        )
        if not source:
            raise RuntimeError("Endpoint sorgente mancante")
        if source.endpoint_type != FileEndpointType.SYNOLOGY:
            raise RuntimeError("Il catalogo du è supportato solo per sorgenti Synology")

        log_row = JobLog(
            job_type="file_replication_catalog",
            job_id=job.id,
            node_name=source.name,
            dataset=",".join(job.source_paths or []),
            status="started",
            message=f"Aggiornamento catalogo du: {job.name}",
        )
        db.add(log_row)
        db.commit()

        run_state = get_run_state(job)
        paths = [sanitize_path(p) for p in (job.source_paths or []) if p]
        if not paths:
            raise RuntimeError("Nessun path sorgente configurato")

        _catalog_progress[job_id] = enrich_rclone_progress_view({
            "status": "catalog_refresh",
            "phase": "starting",
            "phase_label": "Catalogo du Synology",
            "message": "Avvio scansione…",
            **catalog_to_progress_fields(run_state),
        })

        refreshed_paths: list[str] = []
        for src_path in paths:
            if job_id in _catalog_cancel_requested:
                raise CatalogCancelledError("Interrotto dall'utente")

            def _on_du_folder(name: str, idx: int, total: int, _sp: str = src_path) -> None:
                _catalog_progress[job_id] = enrich_rclone_progress_view({
                    **_catalog_progress.get(job_id, {}),
                    "status": "catalog_refresh",
                    "phase": "starting",
                    "phase_label": "Catalogo du Synology",
                    "message": f"du {_sp}: {name} ({idx}/{total})…",
                    **catalog_to_progress_fields(run_state),
                    **folder_progress_to_fields(
                        run_state,
                        _sp,
                        step_path=_sp,
                    ),
                })

            _catalog_progress[job_id] = enrich_rclone_progress_view({
                **_catalog_progress.get(job_id, {}),
                "status": "catalog_refresh",
                "phase": "starting",
                "phase_label": "Catalogo du Synology",
                "message": f"Catalogo 1° livello {src_path}…",
                **catalog_to_progress_fields(run_state),
            })

            du_cat = await synology_du_folder_catalog(
                source,
                src_path,
                exclude_presets=job.exclude_presets or [],
                exclude_patterns=job.exclude_patterns or [],
                on_folder=_on_du_folder,
            )
            if du_cat.get("total_bytes") or du_cat.get("folders"):
                run_state = update_catalog_from_du_folders(run_state, src_path, du_cat)
                assign_run_state(job, run_state)
                db.commit()
                refreshed_paths.append(src_path)
                logger.info(
                    "Catalog refresh job %s %s: %s bytes, %s folders",
                    job_id,
                    src_path,
                    du_cat.get("total_bytes"),
                    du_cat.get("folder_count"),
                )

        duration = int((datetime.utcnow() - started).total_seconds())
        summary = f"Catalogo du aggiornato ({len(refreshed_paths)} path, {duration}s)"
        if log_row:
            log_row.status = "success"
            log_row.message = summary
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
        db.commit()

        fields = catalog_to_progress_fields(run_state)
        for src_path in refreshed_paths:
            fields.update(
                folder_progress_to_fields(run_state, src_path, step_path=src_path)
            )
        _catalog_progress[job_id] = enrich_rclone_progress_view({
            "status": "success",
            "phase": "done",
            "phase_label": "Catalogo du completato",
            "message": summary,
            **fields,
        })

    except CatalogCancelledError:
        duration = int((datetime.utcnow() - started).total_seconds())
        if log_row:
            log_row.status = "cancelled"
            log_row.message = "Aggiornamento catalogo interrotto"
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
            db.commit()
        _catalog_progress[job_id] = {
            **_catalog_progress.get(job_id, {}),
            "status": "cancelled",
            "message": "Aggiornamento catalogo interrotto",
        }
    except Exception as exc:
        logger.error("Catalog refresh job %s fallito: %s", job_id, exc, exc_info=True)
        duration = int((datetime.utcnow() - started).total_seconds())
        if log_row:
            log_row.status = "failed"
            log_row.error = str(exc)
            log_row.message = f"Aggiornamento catalogo fallito: {exc}"
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
            db.commit()
        _catalog_progress[job_id] = {
            "status": "failed",
            "error": str(exc),
            "message": str(exc),
        }
    finally:
        _catalog_running.discard(job_id)
        _catalog_cancel_requested.discard(job_id)
        db.close()
