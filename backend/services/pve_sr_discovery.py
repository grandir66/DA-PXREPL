"""Discovery repliche native Proxmox (pvesr / cluster/replication)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from database import Node, NodeType, RecoveryJob, SyncJob, User
from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


def _parse_pvesr_id(job_id: str) -> tuple[Optional[int], Optional[int]]:
    parts = (job_id or "").split("-")
    vmid = int(parts[0]) if parts and parts[0].isdigit() else None
    jobnum = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return vmid, jobnum


def _node_matches(node: Node, pve_name: str) -> bool:
    if not pve_name:
        return False
    pve = pve_name.strip().lower()
    return node.name.strip().lower() == pve or node.hostname.strip().lower() == pve


def _find_node_by_pve_name(db: Session, pve_name: str) -> Optional[Node]:
    if not pve_name:
        return None
    for node in db.query(Node).filter(Node.node_type == NodeType.PVE.value).all():
        if _node_matches(node, pve_name):
            return node
    return None


async def _ssh_json(node: Node, cmd: str) -> Any:
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
    )
    if not result.success or not (result.stdout or "").strip():
        return None
    return json.loads(result.stdout)


async def fetch_cluster_replication_config(node: Node) -> list[dict]:
    data = await _ssh_json(node, "pvesh get /cluster/replication --output-format json")
    if isinstance(data, list):
        return data
    return []


async def fetch_pvesr_status(node: Node) -> dict[str, dict]:
    data = await _ssh_json(node, "pvesr status --json")
    out: dict[str, dict] = {}
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and row.get("id"):
                out[str(row["id"])] = row
    elif isinstance(data, dict):
        for key, row in data.items():
            if isinstance(row, dict):
                rid = str(row.get("id") or key)
                out[rid] = row
    return out


async def fetch_cluster_vms(node: Node) -> dict[int, dict]:
    data = await _ssh_json(node, "pvesh get /cluster/resources --type vm --output-format json")
    by_vmid: dict[int, dict] = {}
    if not isinstance(data, list):
        return by_vmid
    for row in data:
        if not isinstance(row, dict):
            continue
        vmid = row.get("vmid")
        if vmid is None:
            continue
        try:
            by_vmid[int(vmid)] = row
        except (TypeError, ValueError):
            continue
    return by_vmid


def _link_dapx_jobs(
    db: Session,
    *,
    vmid: int,
    target_pve: str,
    source_pve: Optional[str],
) -> tuple[str, list[dict]]:
    """Ritorna (dapx_link, dapx_jobs[]) dove link è none|syncoid|pve_native|recovery_pbs."""
    target_node = _find_node_by_pve_name(db, target_pve)
    source_node = _find_node_by_pve_name(db, source_pve) if source_pve else None

    matches: list[dict] = []

    for sj in db.query(SyncJob).filter(SyncJob.vm_id == vmid).all():
        dest = db.query(Node).filter(Node.id == sj.dest_node_id).first()
        if target_node and dest and dest.id != target_node.id:
            continue
        if source_node and sj.source_node_id != source_node.id:
            continue
        kind = "pve_native" if sj.sync_method == "pve_native" else "syncoid"
        matches.append({"kind": kind, "id": sj.id, "name": sj.name})

    for rj in db.query(RecoveryJob).filter(RecoveryJob.vm_id == vmid).all():
        dest = db.query(Node).filter(Node.id == rj.dest_node_id).first()
        if target_node and dest and dest.id != target_node.id:
            continue
        matches.append({"kind": "recovery_pbs", "id": rj.id, "name": rj.name})

    if not matches:
        return "none", []
    kinds = {m["kind"] for m in matches}
    if len(kinds) == 1:
        return next(iter(kinds)), matches
    return "mixed", matches


def _enabled_flag(job: dict) -> bool:
    if "enabled" in job:
        return bool(job.get("enabled"))
    if "disable" in job:
        return not bool(job.get("disable"))
    return True


async def discover_pve_sr_jobs(db: Session, user: User) -> list[dict]:
    """Elenca job pvesr sul cluster con stato runtime e collegamento job dapx."""
    node = db.query(Node).filter(Node.node_type == NodeType.PVE.value, Node.is_online == True).first()
    if not node:
        node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    if not node:
        raise ValueError("Nessun nodo PVE configurato")

    config_jobs = await fetch_cluster_replication_config(node)
    status_map = await fetch_pvesr_status(node)
    vms = await fetch_cluster_vms(node)

    items: list[dict] = []
    for job in config_jobs:
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        vmid, jobnum = _parse_pvesr_id(job_id)
        if vmid is None:
            continue

        vm_row = vms.get(vmid) or {}
        source_pve = job.get("source") or vm_row.get("node")
        target_pve = job.get("target") or ""
        status = status_map.get(job_id) or {}

        dapx_link, dapx_jobs = _link_dapx_jobs(
            db,
            vmid=vmid,
            target_pve=target_pve,
            source_pve=source_pve,
        )

        source_node = _find_node_by_pve_name(db, source_pve) if source_pve else None
        target_node = _find_node_by_pve_name(db, target_pve)

        items.append(
            {
                "id": job_id,
                "target": target_pve,
                "vm": vmid,
                "jobnum": jobnum,
                "schedule": job.get("schedule") or "*/15",
                "rate": job.get("rate"),
                "comment": job.get("comment"),
                "enabled": _enabled_flag(job),
                "source": source_pve,
                "vm_name": vm_row.get("name"),
                "vm_type": vm_row.get("type") or "qemu",
                "last_sync": str(status.get("last_sync") or job.get("last_sync") or ""),
                "duration": status.get("duration") or job.get("duration"),
                "fail_count": status.get("fail_count") or job.get("fail_count"),
                "error": status.get("error") or job.get("error"),
                "next_sync": str(status.get("next_sync") or job.get("next_sync") or ""),
                "managed_by": "pvesr",
                "dapx_link": dapx_link,
                "dapx_jobs": dapx_jobs,
                "source_node_id": source_node.id if source_node else None,
                "target_node_id": target_node.id if target_node else None,
                "import_hint": (
                    "pvesr_gestisce_gia"
                    if dapx_link == "none"
                    else "gia_tracciato_dapx"
                ),
                "suggested_dapx_kind": "syncoid",
            }
        )

    return items
