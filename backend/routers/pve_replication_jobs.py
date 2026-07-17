"""
Router per gestione PVE Native Replication (pvesr)
Legge e opera sui job configurati in Proxmox (/cluster/replication).
"""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import json

from database import get_db, Node, User, NodeType
from services.ssh_service import ssh_service
from services.pve_sr_discovery import (
    discover_pve_sr_jobs,
    fetch_cluster_replication_config,
    _find_node_by_pve_name,
)
from routers.auth import get_current_user, require_operator, log_audit

logger = logging.getLogger(__name__)
router = APIRouter()


class PVEReplicationJob(BaseModel):
    id: str
    target: str
    vm: Optional[int] = None
    jobnum: Optional[int] = None
    schedule: Optional[str] = "*/15"
    rate: Optional[float] = None
    comment: Optional[str] = None
    enabled: bool = True
    source: Optional[str] = None
    vm_name: Optional[str] = None
    vm_type: Optional[str] = "qemu"
    last_sync: Optional[str] = None
    duration: Optional[float] = None
    fail_count: Optional[int] = None
    last_try: Optional[str] = None
    error: Optional[str] = None
    next_sync: Optional[str] = None
    managed_by: str = "pvesr"
    dapx_link: Optional[str] = "none"
    dapx_jobs: List[dict] = Field(default_factory=list)
    source_node_id: Optional[int] = None
    target_node_id: Optional[int] = None
    import_hint: Optional[str] = None
    suggested_dapx_kind: Optional[str] = None


class PVEReplicationCreate(BaseModel):
    vmid: int
    target: str
    schedule: Optional[str] = "*/15"
    rate: Optional[float] = None
    comment: Optional[str] = None
    enabled: bool = True


async def _get_cluster_replication_jobs(node: Node) -> List[dict]:
    jobs = await fetch_cluster_replication_config(node)
    return jobs


@router.get("/", response_model=List[PVEReplicationJob])
async def list_replication_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista job replica Proxmox (pvesr) con stato e collegamento job dapx."""
    try:
        items = await discover_pve_sr_jobs(db, user)
        return [PVEReplicationJob(**item) for item in items]
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        logger.error("Errore listing replication jobs: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/discover", response_model=List[PVEReplicationJob])
async def discover_replication_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Alias esplicito per discovery import (stesso payload di GET /)."""
    return await list_replication_jobs(user=user, db=db)


@router.get("/summary")
async def pve_replication_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Conteggi per banner UI Repliche."""
    try:
        items = await discover_pve_sr_jobs(db, user)
    except Exception:
        return {"total": 0, "unlinked": 0, "failed": 0, "enabled": 0}
    unlinked = sum(1 for j in items if j.get("dapx_link") == "none")
    failed = sum(1 for j in items if j.get("error") or (j.get("fail_count") or 0) > 0)
    enabled = sum(1 for j in items if j.get("enabled"))
    return {
        "total": len(items),
        "unlinked": unlinked,
        "failed": failed,
        "enabled": enabled,
    }


@router.post("/", response_model=dict)
async def create_replication_job(
    job: PVEReplicationCreate,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Crea un job pvesr sul cluster Proxmox."""
    if job.vmid < 100:
        raise HTTPException(status_code=400, detail="VMID non valido")

    node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    if not node:
        raise HTTPException(status_code=500, detail="Nessun nodo PVE disponibile")

    try:
        current_jobs = await _get_cluster_replication_jobs(node)
        existing_ids = [
            j["id"]
            for j in current_jobs
            if j.get("guest", j.get("vm")) == job.vmid or j["id"].startswith(f"{job.vmid}-")
        ]

        next_num = 0
        used_nums = []
        for jid in existing_ids:
            try:
                used_nums.append(int(jid.split("-")[1]))
            except Exception:
                pass
        while next_num in used_nums:
            next_num += 1

        job_id = f"{job.vmid}-{next_num}"

        cmd_parts = [
            "pvesh", "create", "/cluster/replication",
            "--id", job_id,
            "--target", job.target,
            "--schedule", f"'{job.schedule}'",
        ]
        if job.rate:
            cmd_parts.extend(["--rate", str(job.rate)])
        if job.comment:
            cmd_parts.extend(["--comment", f"'{job.comment}'"])
        if not job.enabled:
            cmd_parts.extend(["--disable", "1"])

        result = await ssh_service.execute(
            hostname=node.hostname,
            command=" ".join(cmd_parts),
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path,
        )
        if not result.success:
            raise Exception(f"Errore creazione job: {result.stderr}")

        log_audit(db, user.id, "pve_replication_create", "replication", details=f"Created job {job_id} -> {job.target}")
        return {"message": "Job creato", "id": job_id}

    except Exception as e:
        logger.error("Errore creazione replication job: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{job_id}")
async def delete_replication_job(
    job_id: str,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    if not node:
        raise HTTPException(status_code=500, detail="Nessun nodo PVE disponibile")

    try:
        cmd = f"pvesh delete /cluster/replication/{job_id}"
        result = await ssh_service.execute(
            hostname=node.hostname,
            command=cmd,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path,
        )
        if not result.success:
            raise Exception(f"Errore eliminazione job: {result.stderr}")

        log_audit(db, user.id, "pve_replication_delete", "replication", details=f"Deleted job {job_id}")
        return {"message": "Job eliminato"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{job_id}/run")
async def run_replication_job_now(
    job_id: str,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    try:
        jobs = await _get_cluster_replication_jobs(node)
        target_job = next((j for j in jobs if j["id"] == job_id), None)
        if not target_job:
            raise HTTPException(status_code=404, detail="Job non trovato")

        vmid = int(job_id.split("-")[0])

        cmd_res = "pvesh get /cluster/resources --type vm --output-format json"
        res_result = await ssh_service.execute(
            node.hostname, cmd_res, node.ssh_port, node.ssh_user, node.ssh_key_path
        )

        source_node_name = None
        if res_result.success:
            vms = json.loads(res_result.stdout)
            vm = next((v for v in vms if v.get("vmid") == vmid), None)
            if vm:
                source_node_name = vm.get("node")

        if not source_node_name:
            source_node_name = target_job.get("source")
        if not source_node_name:
            raise Exception("Impossibile determinare il nodo sorgente della VM")

        source_node_obj = _find_node_by_pve_name(db, source_node_name)
        if not source_node_obj:
            raise Exception(f"Nodo sorgente '{source_node_name}' non trovato nel DB dapx")

        cmd_run = f"pvesr run --id {job_id}"
        run_result = await ssh_service.execute(
            hostname=source_node_obj.hostname,
            command=cmd_run,
            port=source_node_obj.ssh_port,
            username=source_node_obj.ssh_user,
            key_path=source_node_obj.ssh_key_path,
            timeout=300,
        )
        if not run_result.success:
            raise Exception(f"Errore esecuzione: {run_result.stderr}")

        return {"message": "Replica avviata", "output": run_result.stdout}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Errore run replication: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
