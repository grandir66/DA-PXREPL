"""Risoluzione target VM: indice cluster (con tag e pvesr) + selettori statici/dinamici."""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from database import Node, NodeType
from services.pve_sr_discovery import (
    _find_node_by_pve_name,
    fetch_cluster_replication_config,
)
from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


def _parse_tags(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in str(raw).replace(",", ";").split(";") if t.strip()]


async def fetch_cluster_vm_index(db: Session) -> list[dict]:
    """Indice VM di tutti i cluster raggiungibili, con tag, status e flag pvesr.

    Un solo `pvesh get /cluster/resources --type vm` per cluster: su cluster
    multi-nodo un nodo qualsiasi ritorna TUTTE le VM. Si iterano i nodi PVE
    finché uno risponde; VM deduplicate per (node_id, vmid).
    """
    nodes = (
        db.query(Node)
        .filter(Node.node_type == NodeType.PVE.value, Node.is_active == True)  # noqa: E712
        .all()
    )
    index: list[dict] = []
    seen: set[tuple[int, int]] = set()
    covered_pve_names: set[str] = set()
    pvesr_vmids: set[int] = set()

    for node in nodes:
        if any(_matches_covered(node, name) for name in covered_pve_names):
            continue
        result = await ssh_service.execute(
            hostname=node.hostname,
            command="pvesh get /cluster/resources --type vm --output-format json",
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path,
            timeout=30,
        )
        if not result.success or not (result.stdout or "").strip():
            logger.warning("vm-index: nodo %s non raggiungibile, salto", node.name)
            continue
        try:
            resources = json.loads(result.stdout)
        except ValueError:
            logger.warning("vm-index: output pvesh non valido da %s", node.name)
            continue

        try:
            for entry in await fetch_cluster_replication_config(node):
                guest = entry.get("guest")
                if guest is not None:
                    pvesr_vmids.add(int(guest))
        except Exception:  # noqa: BLE001 — pvesr assente non blocca l'indice
            pass

        for vm in resources:
            pve_node_name = str(vm.get("node") or "")
            covered_pve_names.add(pve_node_name.lower())
            db_node = _find_node_by_pve_name(db, pve_node_name)
            if db_node is None:
                continue  # VM su nodo del cluster non registrato in dapx
            vmid = int(vm.get("vmid"))
            key = (db_node.id, vmid)
            if key in seen:
                continue
            seen.add(key)
            index.append(
                {
                    "node_id": db_node.id,
                    "node_name": db_node.name,
                    "vmid": vmid,
                    "name": vm.get("name") or f"vm-{vmid}",
                    "vm_type": "lxc" if vm.get("type") == "lxc" else "qemu",
                    "status": vm.get("status") or "unknown",
                    "tags": _parse_tags(vm.get("tags")),
                    "has_pvesr": vmid in pvesr_vmids,
                }
            )
    index.sort(key=lambda item: (item["node_name"], item["vmid"]))
    return index


def _matches_covered(node: Node, covered_name: str) -> bool:
    return (
        node.name.strip().lower() == covered_name
        or node.hostname.strip().lower() == covered_name
    )


def apply_selectors(index: list[dict], targets: list[dict], selectors: dict) -> list[dict]:
    """Funzione PURA: union(target statici, match selettori) - esclusioni, con dedup.

    Ogni entry risultato è una riga dell'indice + "source" (static|selector);
    un target statico la cui VM non è più nell'indice produce una entry con
    warning "not_found" (non fatale).
    """
    selectors = selectors or {}
    tags = set(selectors.get("tags") or [])
    node_ids = set(selectors.get("node_ids") or [])
    exclude_vmids = {int(v) for v in (selectors.get("exclude_vmids") or [])}
    by_key = {(vm["node_id"], vm["vmid"]): vm for vm in index}

    resolved: dict[tuple[int, int], dict] = {}

    for target in targets or []:
        key = (int(target["node_id"]), int(target["vmid"]))
        vm = by_key.get(key)
        if vm is None:
            resolved[key] = {
                "node_id": key[0],
                "node_name": target.get("node_name") or "",
                "vmid": key[1],
                "name": target.get("name") or f"vm-{key[1]}",
                "vm_type": target.get("vm_type") or "qemu",
                "status": "unknown",
                "tags": [],
                "has_pvesr": False,
                "source": "static",
                "warning": "not_found",
            }
        else:
            resolved[key] = {**vm, "source": "static"}

    has_dynamic = bool(tags or node_ids)
    if has_dynamic:
        for vm in index:
            key = (vm["node_id"], vm["vmid"])
            if key in resolved:
                continue
            if tags and not (tags & set(vm.get("tags") or [])):
                continue
            if node_ids and vm["node_id"] not in node_ids:
                continue
            resolved[key] = {**vm, "source": "selector"}

    return [
        vm for key, vm in sorted(resolved.items())
        if vm["vmid"] not in exclude_vmids
    ]


async def resolve_targets(db: Session, job) -> list[dict]:
    """Target effettivi del job: indice cluster + selettori."""
    index = await fetch_cluster_vm_index(db)
    return apply_selectors(index, job.targets or [], job.selectors or {})
