"""Helper condivisi per recovery jobs (PBS storage, accesso nodi)."""

from __future__ import annotations

import logging
import shlex

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import Node, RecoveryJob, User, VirtualMachine
from routers.deps import assert_node_access
from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


async def build_vm_name_map(db: Session) -> dict:
    vm_names = {}
    # Usa la cache per ottenere i nomi, molto più veloce di fetch live
    cached_vms = db.query(VirtualMachine).all()
    
    # Se la cache è vuota, potremmo voler triggerare un aggiornamento background?
    # Per ora usiamo quello che c'è per velocità.
    
    for vm in cached_vms:
        # Chiave: "{node_id}-{vmid}"
        key = f"{vm.node_id}-{vm.vmid}"
        vm_names[key] = {"name": vm.name, "type": vm.type}
        
    return vm_names


async def storage_exists(node: Node, storage_id: str) -> bool:
    """Controlla se uno storage esiste sul nodo PVE."""
    cmd = f"pvesm status {storage_id} 2>/dev/null"
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    return result.success


async def ensure_pbs_storage_registered(
    node: Node,
    storage_name: str,
    pbs_node: Node,
    datastore: str
) -> str:
    """Assicura che lo storage PBS sia registrato sul nodo PVE di destinazione."""
    wanted_storage = storage_name or "pbs-backup"
    if await storage_exists(node, wanted_storage):
        return wanted_storage

    repo = datastore or pbs_node.pbs_datastore or "datastore1"

    # Usa pbs_username se configurato, altrimenti fallback a ssh_user@pam
    pbs_user = pbs_node.pbs_username or f"{pbs_node.ssh_user}@pam"
    cmd_parts = [
        "pvesm", "add", "pbs", wanted_storage,
        "--server", pbs_node.hostname,
        "--datastore", repo,
        "--username", pbs_user
    ]
    if pbs_node.pbs_fingerprint:
        # shlex.quote per due punti/metacaratteri senza injection
        cmd_parts.extend(["--fingerprint", shlex.quote(pbs_node.pbs_fingerprint)])
    if pbs_node.pbs_password:
        cmd_parts.extend(["--password", shlex.quote(pbs_node.pbs_password)])

    # Build command with PBS_FINGERPRINT env var prefix if present
    cmd = " ".join(cmd_parts)
    
    # Log the exact command being executed (without password for security)
    safe_cmd = cmd.replace(pbs_node.pbs_password, "***") if pbs_node.pbs_password else cmd
    logger.info(f"PBS storage add command: {safe_cmd}")
    
    if pbs_node.pbs_fingerprint:
        cmd = f'PBS_FINGERPRINT="{pbs_node.pbs_fingerprint}" {cmd}'
    cmd += " 2>&1"
    
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Log full result for debugging
    logger.info(f"PBS storage add result: exit_code={result.exit_code}, stdout={result.stdout}, stderr={result.stderr}")

    if not result.success:
        output = (result.stdout or "").strip() or (result.stderr or "").strip()
        
        # Handle "already defined" as success - storage exists, just reuse it
        if "already defined" in output:
            logger.info(f"Storage {wanted_storage} already exists on {node.name}, reusing it")
            return wanted_storage
        
        logger.error(f"Comando pvesm add output:\n{output}")
        raise Exception(
            f"Errore creazione storage: {output or 'Errore sconosciuto'}"
        )

    return wanted_storage


def require_recovery_node(db: Session, user: User, node_id: int) -> Node:
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    assert_node_access(user, node)
    return node


def assert_recovery_job_access(user: User, job: RecoveryJob, db: Session) -> None:
    """Verifica accesso a tutti i nodi coinvolti in un recovery job."""
    for node_id in (job.source_node_id, job.pbs_node_id, job.dest_node_id):
        node = db.query(Node).filter(Node.id == node_id).first()
        if node:
            assert_node_access(user, node)

