"""Discovery job backup vzdump Proxmox (Datacenter → /cluster/backup) verso storage PBS."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from database import BackupJob, Node, NodeType, User
from services.backup_job_targets import resolve_vm_targets
from services.pve_sr_discovery import (
    _find_node_by_pve_name,
    fetch_cluster_vms,
)
from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


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


def _pick_pve_node(db: Session) -> Optional[Node]:
    node = (
        db.query(Node)
        .filter(Node.node_type == NodeType.PVE.value, Node.is_online == True)
        .first()
    )
    if not node:
        node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    return node


def _enabled_flag(job: dict) -> bool:
    if "enabled" in job:
        return bool(job.get("enabled"))
    if "disable" in job:
        return not bool(job.get("disable"))
    return True


def _parse_vmid_list(raw: Any) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, int):
        return [raw]
    text = str(raw).strip()
    if not text:
        return []
    out: list[int] = []
    for part in re.split(r"[,;\s]+", text):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def _resolve_vmids(job: dict, vms: dict[int, dict]) -> list[int]:
    if job.get("all") in (1, True, "1"):
        return sorted(vms.keys())

    pool = (job.get("pool") or "").strip()
    if pool:
        return sorted(
            vmid
            for vmid, row in vms.items()
            if (row.get("pool") or "").strip() == pool
        )

    vmids = _parse_vmid_list(job.get("vmid"))
    if vmids:
        return vmids

    return _parse_vmid_list(job.get("vmids"))


def _find_pbs_node(db: Session, *, server: str, datastore: str) -> Optional[Node]:
    server_l = (server or "").strip().lower()
    ds_l = (datastore or "").strip().lower()
    candidates = db.query(Node).filter(Node.node_type == NodeType.PBS.value).all()
    for node in candidates:
        host = (node.hostname or "").strip().lower()
        name = (node.name or "").strip().lower()
        node_ds = (node.pbs_datastore or "").strip().lower()
        if server_l and host == server_l:
            if not ds_l or not node_ds or node_ds == ds_l:
                return node
        if server_l and name == server_l:
            if not ds_l or not node_ds or node_ds == ds_l:
                return node
        if ds_l and node_ds == ds_l and not server_l:
            return node
    return candidates[0] if len(candidates) == 1 else None


async def fetch_pbs_storages(node: Node) -> dict[str, dict]:
    """Mappa storage_id → config (solo type=pbs)."""
    data = await _ssh_json(node, "pvesh get /storage --output-format json")
    out: dict[str, dict] = {}
    if not isinstance(data, list):
        return out
    for row in data:
        if not isinstance(row, dict):
            continue
        if (row.get("type") or "").lower() != "pbs":
            continue
        sid = str(row.get("storage") or "")
        if sid:
            out[sid] = row
    return out


async def fetch_cluster_backup_config(node: Node) -> list[dict]:
    data = await _ssh_json(node, "pvesh get /cluster/backup --output-format json")
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _link_dapx_backup_jobs(
    db: Session,
    *,
    vmids: list[int],
    pbs_storage_id: str,
    pbs_node_id: Optional[int],
) -> tuple[str, list[dict]]:
    if not vmids:
        return "none", []

    matches: list[dict] = []
    linked_vmids: set[int] = set()

    for bj in db.query(BackupJob).all():
        if pbs_storage_id and bj.pbs_storage_id and bj.pbs_storage_id != pbs_storage_id:
            continue
        if pbs_node_id and bj.pbs_node_id != pbs_node_id:
            continue
        for t in resolve_vm_targets(bj):
            vid = t.get("vm_id")
            if vid not in vmids or vid in linked_vmids:
                continue
            linked_vmids.add(vid)
            matches.append({"kind": "backup_pbs", "id": bj.id, "name": bj.name, "vm_id": vid})

    if not matches:
        return "none", []
    if len(linked_vmids) >= len(vmids):
        return "backup_pbs", matches
    return "partial", matches


def _vm_labels(vmids: list[int], vms: dict[int, dict]) -> list[dict]:
    labels: list[dict] = []
    for vmid in vmids:
        row = vms.get(vmid) or {}
        labels.append(
            {
                "vm_id": vmid,
                "vm_name": row.get("name"),
                "vm_type": row.get("type") or "qemu",
                "node": row.get("node"),
            }
        )
    return labels


async def discover_pve_pbs_backup_jobs(db: Session, user: User) -> list[dict]:
    """Job vzdump datacenter che usano storage PBS, con collegamento a BackupJob dapx."""
    _ = user  # filtro allowed_nodes applicato in router se necessario
    node = _pick_pve_node(db)
    if not node:
        raise ValueError("Nessun nodo PVE configurato")

    config_jobs = await fetch_cluster_backup_config(node)
    pbs_storages = await fetch_pbs_storages(node)
    vms = await fetch_cluster_vms(node)

    items: list[dict] = []
    for job in config_jobs:
        storage_id = str(job.get("storage") or "").strip()
        if not storage_id:
            continue
        st_cfg = pbs_storages.get(storage_id)
        if not st_cfg:
            continue

        job_id = str(job.get("id") or job.get("upid") or storage_id)
        vmids = _resolve_vmids(job, vms)
        vm_labels = _vm_labels(vmids, vms)

        pbs_server = str(st_cfg.get("server") or "")
        pbs_datastore = str(st_cfg.get("datastore") or st_cfg.get("datastore-name") or "")
        pbs_node = _find_pbs_node(db, server=pbs_server, datastore=pbs_datastore)

        exec_node_name = (job.get("node") or "").strip() or None
        exec_node = _find_node_by_pve_name(db, exec_node_name) if exec_node_name else None

        dapx_link, dapx_jobs = _link_dapx_backup_jobs(
            db,
            vmids=vmids,
            pbs_storage_id=storage_id,
            pbs_node_id=pbs_node.id if pbs_node else None,
        )

        selection = "all" if job.get("all") in (1, True, "1") else None
        if not selection and (job.get("pool") or "").strip():
            selection = f"pool:{job.get('pool')}"
        elif vmids:
            selection = ",".join(str(v) for v in vmids)

        items.append(
            {
                "id": job_id,
                "storage": storage_id,
                "pbs_server": pbs_server or None,
                "pbs_datastore": pbs_datastore or None,
                "schedule": job.get("schedule") or "",
                "mode": job.get("mode") or "snapshot",
                "compress": job.get("compress") or "zstd",
                "enabled": _enabled_flag(job),
                "node": exec_node_name,
                "maxfiles": job.get("maxfiles"),
                "vmids": vmids,
                "vm_count": len(vmids),
                "vm_labels": vm_labels,
                "vm_selection": selection,
                "managed_by": "proxmox",
                "dapx_link": dapx_link,
                "dapx_jobs": dapx_jobs,
                "pbs_node_id": pbs_node.id if pbs_node else None,
                "exec_node_id": exec_node.id if exec_node else None,
                "import_hint": (
                    "gia_tracciato_dapx"
                    if dapx_link == "backup_pbs"
                    else "proxmox_gestisce_gia"
                ),
                "suggested_dapx_kind": "backup_pbs",
            }
        )

    return items
