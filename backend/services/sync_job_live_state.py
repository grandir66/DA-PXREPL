"""Stato live job sync (syncoid attivo, progresso trasferimento)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from database import Node, SyncJob, SyncMethod
from services.scheduler import scheduler_service
from services.syncoid_service import syncoid_service

logger = logging.getLogger(__name__)


async def get_sync_job_live_state(
    job: SyncJob,
    source_node: Node,
    dest_node: Node,
) -> Dict[str, Any]:
    """Stato live da nodi remoti (syncoid/receive attivo + percentuale)."""
    sync_method = job.sync_method or SyncMethod.SYNCOID.value
    if sync_method in (SyncMethod.BTRFS_SEND.value, SyncMethod.PVE_NATIVE.value):
        return {
            "is_replicating": False,
            "transfer_progress": None,
            "last_status": job.last_status,
            "current_status": getattr(job, "current_status", None),
        }

    job_key = f"sync_{job.id}"
    in_mem = scheduler_service.is_running(job_key)
    db_running = (job.last_status or "").lower() == "running"
    is_replicating = in_mem or db_running

    if not is_replicating and (job.last_status or "").lower() in ("failed", "running"):
        try:
            is_replicating = await syncoid_service.is_replication_active(
                executor_host=source_node.hostname,
                executor_port=source_node.ssh_port,
                executor_user=source_node.ssh_user,
                executor_key=source_node.ssh_key_path,
                source_dataset=job.source_dataset,
                dest_host=dest_node.hostname,
                dest_port=dest_node.ssh_port,
                dest_user=dest_node.ssh_user,
                dest_key=dest_node.ssh_key_path,
                dest_dataset=job.dest_dataset,
            )
        except Exception as e:
            logger.debug("live state job %s: %s", job.id, e)

    transfer_progress = None
    if is_replicating:
        try:
            transfer_progress = await syncoid_service.get_replication_progress(
                executor_host=source_node.hostname,
                executor_port=source_node.ssh_port,
                executor_user=source_node.ssh_user,
                executor_key=source_node.ssh_key_path,
                source_dataset=job.source_dataset,
                dest_host=dest_node.hostname,
                dest_port=dest_node.ssh_port,
                dest_user=dest_node.ssh_user,
                dest_key=dest_node.ssh_key_path,
                dest_dataset=job.dest_dataset,
            )
        except Exception as e:
            logger.debug("transfer_progress list job %s: %s", job.id, e)

    last_status = job.last_status
    current_status = getattr(job, "current_status", None)
    if is_replicating:
        last_status = "running"
        current_status = "running"

    return {
        "is_replicating": is_replicating,
        "transfer_progress": transfer_progress,
        "last_status": last_status,
        "current_status": current_status,
    }


async def compute_vm_group_progress(
    group_jobs: List[SyncJob],
    live_by_id: Dict[int, Dict[str, Any]],
    nodes_by_id: Dict[int, Node],
) -> Optional[Dict[str, Any]]:
    """Progresso cumulativo su tutti i dischi del gruppo VM."""
    total_source = 0
    total_dest = 0
    disks_done = 0
    disks_total = len(group_jobs)

    for job in group_jobs:
        st = (live_by_id.get(job.id, {}).get("last_status") or job.last_status or "").lower()
        if st == "success":
            disks_done += 1

        source_node = nodes_by_id.get(job.source_node_id)
        dest_node = nodes_by_id.get(job.dest_node_id)
        if not source_node or not dest_node:
            continue

        prog = live_by_id.get(job.id, {}).get("transfer_progress")
        if not prog:
            try:
                prog = await syncoid_service.get_replication_progress(
                    executor_host=source_node.hostname,
                    executor_port=source_node.ssh_port,
                    executor_user=source_node.ssh_user,
                    executor_key=source_node.ssh_key_path,
                    source_dataset=job.source_dataset,
                    dest_host=dest_node.hostname,
                    dest_port=dest_node.ssh_port,
                    dest_user=dest_node.ssh_user,
                    dest_key=dest_node.ssh_key_path,
                    dest_dataset=job.dest_dataset,
                )
            except Exception:
                prog = None

        if prog:
            total_source += int(prog.get("source_bytes") or 0)
            total_dest += int(prog.get("dest_bytes") or 0)

    if total_source <= 0:
        return None

    percent = min(100.0, round((total_dest / total_source) * 100.0, 1))
    src_h = syncoid_service.format_bytes(total_source)
    dst_h = syncoid_service.format_bytes(total_dest)
    return {
        "percent": percent,
        "source_bytes": total_source,
        "dest_bytes": total_dest,
        "source_human": src_h,
        "dest_human": dst_h,
        "disks_done": disks_done,
        "disks_total": disks_total,
        "label": f"{dst_h} / {src_h} — {disks_done}/{disks_total} dischi ({percent}%)",
    }
