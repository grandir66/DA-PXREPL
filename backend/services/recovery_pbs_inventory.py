"""Contesto inventario PBS per API recovery."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import Node, NodeType, User
from routers.deps import assert_node_access
from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


async def resolve_pbs_inventory_context(
    db: Session,
    user: User,
    node_id: int,
    datastore: Optional[str] = None,
    pve_node_id: Optional[int] = None,
    pbs_storage: Optional[str] = None,
):
    """Risolve nodo PBS, datastore, nodo PVE e storage per inventario."""
    node = db.query(Node).filter(
        Node.id == node_id,
        Node.node_type == NodeType.PBS.value
    ).first()

    if not node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    assert_node_access(user, node)

    ds = datastore or node.pbs_datastore or "datastore1"
    pve_node = None
    storage_name = pbs_storage

    if pve_node_id:
        pve_node = db.query(Node).filter(
            Node.id == pve_node_id,
            Node.node_type == NodeType.PVE.value
        ).first()
        if pve_node:
            assert_node_access(user, pve_node)
    else:
        pve_node = db.query(Node).filter(
            Node.node_type == NodeType.PVE.value
        ).first()

    if pve_node and not storage_name:
        storage_result = await ssh_service.execute(
            hostname=pve_node.hostname,
            command="pvesm status 2>/dev/null",
            port=pve_node.ssh_port,
            username=pve_node.ssh_user,
            key_path=pve_node.ssh_key_path
        )
        if storage_result.success and storage_result.stdout:
            for line in storage_result.stdout.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "pbs" and parts[2] == "active":
                    storage_name = parts[0]
                    logger.info(f"Trovato storage PBS: {storage_name}")
                    break

    return node, ds, pve_node, storage_name
