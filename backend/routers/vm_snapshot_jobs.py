"""Router job Snapshot VM (/api/vm-snapshots)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import JobLog, Node, get_db
from routers.auth import User, get_current_user, require_operator
from services.proxmox_service import proxmox_service
from services.scheduler import scheduler_service
from services.vm_snapshot.execution import (
    execute_vm_snapshot_job,
    get_job_progress,
    is_job_running,
)
from services.vm_snapshot.models import VmSnapshotJob
from services.vm_snapshot.naming import parse_snapshot_name
from services.vm_snapshot.resolver import (
    apply_selectors,
    fetch_cluster_vm_index,
    resolve_targets,
)
from services.vm_snapshot.schemas import (
    Selectors,
    TargetRef,
    VmSnapshotJobCreate,
    VmSnapshotJobOut,
    VmSnapshotJobUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _allowed_node_ids(user: User) -> Optional[set]:
    """Insieme dei node_id accessibili all'utente, o None se illimitato (admin/allowed_nodes null)."""
    if getattr(user, "role", None) == "admin" or getattr(user, "allowed_nodes", None) is None:
        return None
    return set(user.allowed_nodes)


def _filter_index_for_user(user: User, index: list[dict]) -> list[dict]:
    allowed = _allowed_node_ids(user)
    if allowed is None:
        return index
    return [e for e in index if e.get("node_id") in allowed]


def _assert_targets_allowed(user: User, targets: list, selectors) -> None:
    """S-10: un operator con allowed_nodes non può creare job su nodi fuori perimetro."""
    allowed = _allowed_node_ids(user)
    if allowed is None:
        return
    bad = [t.node_id for t in (targets or []) if t.node_id not in allowed]
    bad += [n for n in (selectors.node_ids or []) if n not in allowed]
    if bad:
        raise HTTPException(
            status_code=403,
            detail=f"Nodi non consentiti per l'utente: {sorted(set(bad))}",
        )


def _latest_log_errors(db: Session, job_ids: list[int]) -> dict[int, str]:
    if not job_ids:
        return {}
    logs = (
        db.query(JobLog)
        .filter(JobLog.job_type == "vm_snapshot", JobLog.job_id.in_(job_ids))
        .order_by(JobLog.job_id, JobLog.id.desc())
        .all()
    )
    latest: dict[int, JobLog] = {}
    for log in logs:
        latest.setdefault(log.job_id, log)
    return {
        jid: (log.error or log.message or "")
        for jid, log in latest.items()
        if log.status == "failed"
    }


def _label_conflicts(db: Session, job: VmSnapshotJob) -> list[str]:
    """Altri job attivi con lo stesso label: retention incrociata se i target si sovrappongono."""
    others = (
        db.query(VmSnapshotJob)
        .filter(
            VmSnapshotJob.label == job.label,
            VmSnapshotJob.id != job.id,
            VmSnapshotJob.is_active == True,  # noqa: E712
        )
        .all()
    )
    return [other.name for other in others]


def _job_out(db: Session, job: VmSnapshotJob, last_run_error: Optional[str] = None) -> VmSnapshotJobOut:
    return VmSnapshotJobOut(
        id=job.id,
        name=job.name,
        description=job.description,
        label=job.label,
        keep=job.keep,
        include_vmstate=bool(job.include_vmstate),
        targets=job.targets or [],
        selectors=job.selectors or {},
        schedule=job.schedule,
        schedule_config=job.schedule_config,
        is_active=bool(job.is_active),
        current_status=job.current_status,
        last_run_at=job.last_run_at,
        last_run_status=job.last_run_status,
        last_run_duration_sec=job.last_run_duration_sec,
        next_run_at=scheduler_service.next_run_for(f"vm_snapshot_{job.id}") or job.next_run_at,
        notify_mode=job.notify_mode,
        notify_subject=job.notify_subject,
        run_state=job.run_state or {},
        last_run_error=last_run_error,
        label_conflicts=_label_conflicts(db, job),
    )


@router.get("/stats/summary")
def stats_summary(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    total = db.query(VmSnapshotJob).count()
    active = db.query(VmSnapshotJob).filter(VmSnapshotJob.is_active == True).count()  # noqa: E712
    running = db.query(VmSnapshotJob).filter(VmSnapshotJob.current_status == "running").count()
    failed = db.query(VmSnapshotJob).filter(
        VmSnapshotJob.last_run_status.in_(["failed", "partial"])
    ).count()
    return {"total": total, "active": active, "running": running, "failed": failed}


@router.get("/vm-index")
async def vm_index(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Indice VM cluster con tag, status e flag pvesr (per il wizard di selezione).

    S-10: filtrato per allowed_nodes dell'utente."""
    return _filter_index_for_user(user, await fetch_cluster_vm_index(db))


@router.post("/resolve-preview")
async def resolve_preview(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Anteprima VM risolte da targets+selectors (dry-run per il wizard)."""
    targets = [TargetRef(**t).model_dump() for t in body.get("targets") or []]
    selectors = Selectors(**(body.get("selectors") or {})).model_dump()
    index = _filter_index_for_user(user, await fetch_cluster_vm_index(db))
    return apply_selectors(index, targets, selectors)


@router.get("", response_model=list[VmSnapshotJobOut])
def list_jobs(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    jobs = db.query(VmSnapshotJob).order_by(VmSnapshotJob.name).all()
    errors = _latest_log_errors(db, [j.id for j in jobs])
    return [
        _job_out(db, j, None if j.current_status == "running" else errors.get(j.id))
        for j in jobs
    ]


@router.post("", response_model=VmSnapshotJobOut)
def create_job(
    body: VmSnapshotJobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
):
    if not body.targets and not (body.selectors.tags or body.selectors.node_ids):
        raise HTTPException(
            status_code=400,
            detail="Selezionare almeno una VM o un selettore (tag/nodo)",
        )
    _assert_targets_allowed(user, body.targets, body.selectors)
    job = VmSnapshotJob(
        name=body.name,
        description=body.description,
        label=body.label,
        keep=body.keep,
        include_vmstate=body.include_vmstate,
        targets=[t.model_dump() for t in body.targets],
        selectors=body.selectors.model_dump(),
        schedule=body.schedule,
        schedule_config=body.schedule_config,
        is_active=body.is_active,
        notify_mode=body.notify_mode,
        notify_subject=body.notify_subject,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    if job.schedule and job.is_active:
        scheduler_service.update_vm_snapshot_schedule(job.id, job.schedule)
    return _job_out(db, job)


@router.get("/{job_id}", response_model=VmSnapshotJobOut)
def get_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    job = db.query(VmSnapshotJob).filter(VmSnapshotJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    # B19: come list_jobs, includi l'ultimo errore (se il job non è in esecuzione).
    err = None if job.current_status == "running" else _latest_log_errors(db, [job.id]).get(job.id)
    return _job_out(db, job, err)


@router.put("/{job_id}", response_model=VmSnapshotJobOut)
def update_job(
    job_id: int,
    body: VmSnapshotJobUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(VmSnapshotJob).filter(VmSnapshotJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    data = body.model_dump(exclude_unset=True)
    if "targets" in data and data["targets"] is not None:
        data["targets"] = [TargetRef(**t).model_dump() for t in data["targets"]]
    if "selectors" in data and data["selectors"] is not None:
        data["selectors"] = Selectors(**data["selectors"]).model_dump()
    # B8: come in create, la selezione finale non può restare vuota.
    final_targets = data.get("targets", job.targets) or []
    final_selectors = data.get("selectors", job.selectors) or {}
    if not final_targets and not (final_selectors.get("tags") or final_selectors.get("node_ids")):
        raise HTTPException(
            status_code=400,
            detail="Selezionare almeno una VM o un selettore (tag/nodo)",
        )
    for key, value in data.items():
        setattr(job, key, value)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    if job.schedule and job.is_active:
        scheduler_service.update_vm_snapshot_schedule(job.id, job.schedule)
    else:
        scheduler_service.remove_vm_snapshot_schedule(job.id)
    return _job_out(db, job)


@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(VmSnapshotJob).filter(VmSnapshotJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    # B9: non eliminare un job mentre sta girando (lascerebbe l'esecuzione orfana).
    if is_job_running(job_id) or job.current_status == "running":
        raise HTTPException(status_code=409, detail="Job in esecuzione: fermarlo prima di eliminarlo")
    scheduler_service.remove_vm_snapshot_schedule(job.id)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.post("/{job_id}/run")
async def run_job(
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_operator),
):
    job = db.query(VmSnapshotJob).filter(VmSnapshotJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    if is_job_running(job_id) or job.current_status == "running":
        raise HTTPException(status_code=409, detail="Job già in esecuzione")
    asyncio.create_task(execute_vm_snapshot_job(job_id))
    return {"ok": True, "message": "Esecuzione snapshot avviata"}


@router.post("/{job_id}/toggle", response_model=VmSnapshotJobOut)
def toggle_job(job_id: int, db: Session = Depends(get_db), _user: User = Depends(require_operator)):
    job = db.query(VmSnapshotJob).filter(VmSnapshotJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    job.is_active = not job.is_active
    db.commit()
    db.refresh(job)
    if job.is_active and job.schedule:
        scheduler_service.update_vm_snapshot_schedule(job.id, job.schedule)
    else:
        scheduler_service.remove_vm_snapshot_schedule(job.id)
    return _job_out(db, job)


@router.get("/{job_id}/logs")
def job_logs(job_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    logs = (
        db.query(JobLog)
        .filter(JobLog.job_type == "vm_snapshot", JobLog.job_id == job_id)
        .order_by(JobLog.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": log.id,
            "status": log.status,
            "message": log.message,
            "output": log.output,
            "error": log.error,
            "duration": log.duration,
            "created_at": log.started_at,
            "completed_at": log.completed_at,
        }
        for log in logs
    ]


@router.get("/{job_id}/progress")
def job_progress(job_id: int, _user: User = Depends(get_current_user)):
    prog = get_job_progress(job_id)
    if prog:
        return prog
    return {"status": "idle"}


@router.get("/{job_id}/snapshots")
async def job_snapshots(
    job_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Vista aggregata: per ogni VM del job, gli snapshot esistenti (con flag is_module)."""
    job = db.query(VmSnapshotJob).filter(VmSnapshotJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    targets = await resolve_targets(db, job)
    nodes = {
        n.id: n
        for n in db.query(Node)
        .filter(Node.id.in_(list({t["node_id"] for t in targets})))
        .all()
    }
    out = []
    for target in targets:
        node = nodes.get(target["node_id"])
        entry = {
            "node_id": target["node_id"],
            "node_name": target.get("node_name"),
            "vmid": target["vmid"],
            "vm_name": target.get("name"),
            "vm_type": target.get("vm_type") or "qemu",
            "status": target.get("status"),
            "has_pvesr": bool(target.get("has_pvesr")),
            "snapshots": [],
            "error": None,
        }
        if node is None or target.get("warning") == "not_found":
            entry["error"] = "VM non trovata"
            out.append(entry)
            continue
        try:
            snapshots = await proxmox_service.get_snapshots(
                hostname=node.hostname,
                vmid=target["vmid"],
                vm_type=entry["vm_type"],
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path,
            )
        except Exception as exc:  # noqa: BLE001 — un nodo irraggiungibile non svuota la vista
            entry["error"] = str(exc)
            out.append(entry)
            continue
        for snap in snapshots:
            parsed = parse_snapshot_name(snap.get("name") or "")
            entry["snapshots"].append(
                {
                    "name": snap.get("name"),
                    "snaptime": snap.get("snaptime"),
                    "description": snap.get("description"),
                    "vmstate": bool(snap.get("vmstate")),
                    "is_module": parsed is not None,
                    "label": parsed[0] if parsed else None,
                }
            )
        entry["snapshots"].sort(key=lambda s: s.get("snaptime") or 0, reverse=True)
        out.append(entry)
    return out
