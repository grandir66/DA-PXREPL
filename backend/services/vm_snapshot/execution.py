"""Esecuzione job Snapshot VM: snapshot per ogni target risolto + retention, esiti per-VM."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from database import JobLog, Node, SessionLocal
from services.proxmox_service import proxmox_service
from services.vm_snapshot.models import VmSnapshotJob
from services.vm_snapshot.naming import build_description, build_snapshot_name
from services.vm_snapshot.resolver import resolve_targets
from services.vm_snapshot.retention import prune_vm

logger = logging.getLogger(__name__)

_RUNNING: dict[int, dict] = {}
_NODE_PARALLELISM = 3


def is_job_running(job_id: int) -> bool:
    return job_id in _RUNNING


def get_job_progress(job_id: int) -> Optional[dict]:
    return _RUNNING.get(job_id)


def reconcile_stale_running_jobs() -> int:
    """All'avvio backend: job 'running' in DB senza run in memoria → idle."""
    db = SessionLocal()
    reset = 0
    try:
        jobs = db.query(VmSnapshotJob).filter(VmSnapshotJob.current_status == "running").all()
        for job in jobs:
            if job.id not in _RUNNING:
                job.current_status = "idle"
                reset += 1
        if reset:
            db.commit()
    finally:
        db.close()
    return reset


async def _snapshot_one_vm(
    node: Node,
    target: dict,
    job: VmSnapshotJob,
    snapname: str,
) -> dict:
    """Snapshot + retention su una singola VM. Non solleva: ogni errore finisce nel result."""
    result: dict = {
        "node_id": target["node_id"],
        "node_name": target.get("node_name") or node.name,
        "vmid": target["vmid"],
        "vm_name": target.get("name"),
        "vm_type": target.get("vm_type") or "qemu",
        "snapname": snapname,
        "created": False,
        "pruned": [],
        "warning": None,
        "error": None,
    }
    if target.get("warning") == "not_found":
        result["error"] = "VM non trovata nell'indice cluster (rimossa o nodo offline)"
        return result
    if target.get("has_pvesr"):
        result["warning"] = (
            "VM con replica pvesr attiva: pvesr può rimuovere snapshot non suoi "
            "e un rollback può invalidare la replica"
        )

    vm_type = result["vm_type"]
    vmstate = bool(job.include_vmstate) and vm_type == "qemu"
    try:
        ok, message = await proxmox_service.create_snapshot(
            hostname=node.hostname,
            vmid=target["vmid"],
            snapname=snapname,
            description=build_description(job.id, job.name, job.label),
            vmstate=vmstate,
            vm_type=vm_type,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path,
        )
        if not ok:
            result["error"] = message
            return result
        result["created"] = True

        pruned, prune_errors = await prune_vm(
            node, target["vmid"], vm_type, job.label, job.keep
        )
        result["pruned"] = pruned
        if prune_errors:
            note = "retention parziale: " + "; ".join(prune_errors)
            result["warning"] = f"{result['warning']} — {note}" if result["warning"] else note
    except Exception as exc:  # noqa: BLE001 — l'errore su una VM non ferma le altre
        logger.error(
            "vm_snapshot job %s: errore su VM %s@%s: %s",
            job.id, target["vmid"], node.name, exc, exc_info=True,
        )
        result["error"] = str(exc)
    return result


async def _run_node_batch(
    node: Node,
    targets: list[dict],
    job: VmSnapshotJob,
    snapname: str,
    job_id: int,
    progress_lock: asyncio.Lock,
) -> list[dict]:
    """Sequenziale dentro il nodo: un solo qm/pct alla volta per host."""
    results: list[dict] = []
    for target in targets:
        async with progress_lock:
            prog = _RUNNING.get(job_id)
            if prog is not None:
                prog["current"] = int(prog.get("current") or 0) + 1
                prog["vm"] = f"{target.get('name') or ''} ({target['vmid']}) @ {node.name}"
        results.append(await _snapshot_one_vm(node, target, job, snapname))
    return results


def _summarize(results: list[dict]) -> tuple[str, dict]:
    ok = sum(1 for r in results if r.get("created"))
    failed = sum(1 for r in results if r.get("error"))
    pruned_total = sum(len(r.get("pruned") or []) for r in results)
    if not results or ok == 0:
        status = "failed"
    elif failed:
        status = "partial"
    else:
        status = "success"
    return status, {"ok": ok, "failed": failed, "pruned_total": pruned_total}


def _result_lines(results: list[dict]) -> list[str]:
    lines = []
    for r in results:
        head = f"[{r['node_name']}] {r.get('vm_name') or ''} ({r['vmid']}, {r['vm_type']})"
        if r.get("error"):
            lines.append(f"{head}: ERRORE — {r['error']}")
            continue
        parts = [f"snapshot {r['snapname']} creato"]
        if r.get("pruned"):
            parts.append(f"potati {len(r['pruned'])}: {', '.join(r['pruned'])}")
        if r.get("warning"):
            parts.append(f"avviso: {r['warning']}")
        lines.append(f"{head}: " + " — ".join(parts))
    return lines


async def execute_vm_snapshot_job(job_id: int, *, is_scheduled: bool = False) -> None:
    if job_id in _RUNNING:
        logger.warning("VmSnapshotJob %s già in esecuzione", job_id)
        return
    _RUNNING[job_id] = {"status": "running", "phase": "resolve", "current": 0, "total": 0}
    started = datetime.utcnow()
    db = SessionLocal()
    log_row: Optional[JobLog] = None
    results: list[dict] = []

    try:
        job = db.query(VmSnapshotJob).filter(VmSnapshotJob.id == job_id).first()
        if not job:
            logger.error("VmSnapshotJob %s non trovato", job_id)
            return

        job.current_status = "running"
        db.commit()
        log_row = JobLog(
            job_type="vm_snapshot",
            job_id=job.id,
            dataset=job.label,
            status="started",
            message=f"Avvio snapshot VM: {job.name} [label={job.label} keep={job.keep}]",
        )
        db.add(log_row)
        db.commit()

        targets = await resolve_targets(db, job)
        if not targets:
            raise RuntimeError(
                "Nessuna VM da processare: la selezione (checkbox + selettori) è vuota"
            )

        snapname = build_snapshot_name(job.label, datetime.utcnow())
        by_node: dict[int, list[dict]] = {}
        for target in targets:
            by_node.setdefault(target["node_id"], []).append(target)
        nodes = {
            n.id: n
            for n in db.query(Node).filter(Node.id.in_(list(by_node.keys()))).all()
        }

        _RUNNING[job_id].update({"phase": "snapshot", "total": len(targets), "current": 0})
        progress_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(_NODE_PARALLELISM)

        async def _node_task(node_id: int, node_targets: list[dict]) -> list[dict]:
            node = nodes.get(node_id)
            if node is None:
                return [
                    {**t, "vm_name": t.get("name"), "snapname": snapname, "created": False,
                     "pruned": [], "warning": None,
                     "error": "Nodo non trovato nel database"}
                    for t in node_targets
                ]
            async with semaphore:
                return await _run_node_batch(
                    node, node_targets, job, snapname, job_id, progress_lock
                )

        batches = await asyncio.gather(
            *[_node_task(nid, tgts) for nid, tgts in by_node.items()]
        )
        for batch in batches:
            results.extend(batch)
        results.sort(key=lambda r: (r["node_name"], r["vmid"]))

        status, summary = _summarize(results)
        duration = int((datetime.utcnow() - started).total_seconds())
        job.run_state = {"results": results, "summary": summary, "snapname": snapname}
        job.last_run_at = datetime.utcnow()
        job.last_run_status = status
        job.last_run_duration_sec = duration
        job.current_status = "idle"
        db.commit()

        if log_row:
            log_row.status = "success" if status == "success" else ("warning" if status == "partial" else "failed")
            log_row.message = (
                f"Snapshot {snapname}: {summary['ok']}/{len(results)} VM ok, "
                f"{summary['pruned_total']} potati ({duration}s)"
            )
            log_row.output = "\n".join(_result_lines(results))
            if status != "success":
                log_row.error = "; ".join(
                    f"{r.get('vm_name') or r['vmid']}: {r['error']}"
                    for r in results if r.get("error")
                )[:2000]
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
            db.commit()

        _RUNNING[job_id] = {
            "status": status,
            "phase": "done",
            "total": len(results),
            "current": len(results),
            "summary": summary,
        }
        from services.vm_snapshot.notifications import notify_vm_snapshot_result

        await notify_vm_snapshot_result(
            job, status=status, duration=duration, results=results,
            is_scheduled=is_scheduled,
        )

    except Exception as exc:  # noqa: BLE001 — qualunque errore chiude il run come failed
        logger.error("VmSnapshotJob %s fallito: %s", job_id, exc, exc_info=True)
        duration = int((datetime.utcnow() - started).total_seconds())
        err_text = str(exc)
        job = db.query(VmSnapshotJob).filter(VmSnapshotJob.id == job_id).first()
        if job:
            job.last_run_at = datetime.utcnow()
            job.last_run_status = "failed"
            job.last_run_duration_sec = duration
            job.current_status = "idle"
            if results:
                job.run_state = {"results": results, "summary": _summarize(results)[1]}
        if log_row:
            log_row.status = "failed"
            log_row.error = err_text
            log_row.duration = duration
            log_row.completed_at = datetime.utcnow()
        db.commit()
        _RUNNING[job_id] = {"status": "failed", "error": err_text}
        if job:
            from services.vm_snapshot.notifications import notify_vm_snapshot_result

            await notify_vm_snapshot_result(
                job, status="failed", duration=duration, results=results,
                error=err_text, is_scheduled=is_scheduled,
            )
    finally:
        final = _RUNNING.pop(job_id, None)
        # L'ultimo stato resta consultabile via run_state/JobLog; il registry è solo live.
        del final
        db.close()
