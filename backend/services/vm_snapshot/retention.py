"""Retention snapshot del modulo: pota oltre `keep` SOLO i nomi propri (prefisso+label)."""

from __future__ import annotations

import logging
from datetime import datetime

from database import Node
from services.proxmox_service import proxmox_service
from services.vm_snapshot.naming import parse_snapshot_name

logger = logging.getLogger(__name__)


def select_prunable(snapshots: list[dict], label: str, keep: int) -> list[str]:
    """Nomi da cancellare: snapshot del modulo con questo label, oltre i `keep` più recenti.

    Snapshot manuali, di altri label o di altri tool non matchano la regex e sono
    invisibili (un nome ambiguo/malformato NON viene mai cancellato).
    Ordinamento per timestamp nel nome: unica sorgente cross-nodo, indipendente
    dal clock dei nodi.
    """
    owned: list[tuple[datetime, str]] = []
    for snap in snapshots or []:
        name = snap.get("name") or ""
        parsed = parse_snapshot_name(name)
        if not parsed or parsed[0] != label:
            continue
        owned.append((parsed[1], name))
    owned.sort(key=lambda item: item[0], reverse=True)
    if keep < 1:
        keep = 1
    return [name for _, name in owned[keep:]]


async def prune_vm(
    node: Node,
    vmid: int,
    vm_type: str,
    label: str,
    keep: int,
) -> tuple[list[str], list[str]]:
    """Applica la retention su una VM. Ritorna (nomi_potati, errori)."""
    snapshots = await proxmox_service.get_snapshots(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
    )
    pruned: list[str] = []
    errors: list[str] = []
    for snapname in select_prunable(snapshots, label, keep):
        ok, message = await proxmox_service.delete_snapshot(
            hostname=node.hostname,
            vmid=vmid,
            snapname=snapname,
            vm_type=vm_type,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path,
        )
        if ok:
            pruned.append(snapname)
        else:
            errors.append(f"{snapname}: {message}")
    return pruned, errors
