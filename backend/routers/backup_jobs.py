"""
Router per gestione Backup Jobs verso PBS
Solo backup, senza restore automatico
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
import asyncio
import logging
import re

from database import (
    get_db, Node, BackupJob, BackupJobStatus, JobLog, NodeType
)
from routers.auth import get_current_user, require_operator, User, log_audit
from services import ssh_service
from services.schedule_translator import to_cron as _sched_to_cron, from_cron as _sched_from_cron
from services.scheduler import scheduler_service
from services.pve_backup_discovery import discover_pve_pbs_backup_jobs
from services.pve_sr_discovery import _find_node_by_pve_name
from services.backup_job_targets import (
    normalize_vm_targets,
    resolve_vm_targets,
    job_targets_summary,
)


def _resolve_schedule_pair(schedule: Optional[str], schedule_config: Optional[Dict[str, Any]]):
    """Allinea cron e schedule_config (vedi sync_jobs._resolve_schedule_pair)."""
    if schedule_config is not None:
        try:
            cron = _sched_to_cron(schedule_config)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"schedule_config non valido: {e}")
        return cron, schedule_config
    if schedule is not None:
        cron = schedule.strip() or None
        cfg = _sched_from_cron(cron) if cron else {"kind": "manual"}
        return cron, cfg
    return None, None

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== SCHEMAS ==============

class VmBackupTarget(BaseModel):
    vm_id: int = Field(..., ge=100, le=999999999)
    vm_type: str = "qemu"
    vm_name: Optional[str] = None
    source_node_id: int


class BackupJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_node_id: Optional[int] = None
    vm_id: Optional[int] = Field(None, ge=100, le=999999999)
    vm_type: str = "qemu"
    vm_name: Optional[str] = None
    vm_targets: Optional[List[VmBackupTarget]] = None
    pbs_node_id: int
    pbs_datastore: Optional[str] = None
    pbs_storage_id: Optional[str] = None
    backup_mode: str = "snapshot"
    backup_compress: str = "zstd"
    include_all_disks: bool = True
    bandwidth_limit: Optional[int] = None
    keep_last: int = 3
    keep_daily: Optional[int] = None
    keep_weekly: Optional[int] = None
    keep_monthly: Optional[int] = None
    schedule: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    is_active: bool = True
    notify_on_each_run: bool = False
    notify_on_failure: bool = True

    @model_validator(mode="after")
    def validate_vm_selection(self):
        if self.vm_targets and len(self.vm_targets) >= 1:
            return self
        if self.vm_id is not None and self.source_node_id is not None:
            return self
        raise ValueError(
            "Specificare vm_targets (lista VM) oppure vm_id e source_node_id"
        )
    
    @field_validator('backup_mode')
    @classmethod
    def validate_backup_mode(cls, v):
        if v not in ['snapshot', 'stop', 'suspend']:
            raise ValueError('backup_mode deve essere: snapshot, stop, suspend')
        return v
    
    @field_validator('backup_compress')
    @classmethod
    def validate_compress(cls, v):
        if v not in ['none', 'lzo', 'gzip', 'zstd']:
            raise ValueError('backup_compress deve essere: none, lzo, gzip, zstd')
        return v
    
    @field_validator('schedule')
    @classmethod
    def validate_schedule(cls, v):
        if v is None or v == '':
            return None
        # Valida formato cron base
        cron_pattern = r'^(\*|[0-9,\-\/]+)\s+(\*|[0-9,\-\/]+)\s+(\*|[0-9,\-\/]+)\s+(\*|[0-9,\-\/]+)\s+(\*|[0-9,\-\/]+)$'
        if not re.match(cron_pattern, v):
            raise ValueError('schedule deve essere in formato cron valido')
        return v


class BackupJobUpdate(BaseModel):
    name: Optional[str] = None
    vm_targets: Optional[List[VmBackupTarget]] = None
    vm_name: Optional[str] = None
    pbs_datastore: Optional[str] = None
    pbs_storage_id: Optional[str] = None
    backup_mode: Optional[str] = None
    backup_compress: Optional[str] = None
    include_all_disks: Optional[bool] = None
    bandwidth_limit: Optional[int] = None
    keep_last: Optional[int] = None
    keep_daily: Optional[int] = None
    keep_weekly: Optional[int] = None
    keep_monthly: Optional[int] = None
    schedule: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    notify_on_each_run: Optional[bool] = None
    notify_on_failure: Optional[bool] = None


class BackupJobResponse(BaseModel):
    id: int
    name: str
    source_node_id: int
    source_node_name: Optional[str] = None
    vm_id: int
    vm_type: str
    vm_name: Optional[str] = None
    vm_targets: Optional[List[dict]] = None
    vm_count: int = 1
    vm_summary: Optional[str] = None
    pbs_node_id: int
    pbs_node_name: Optional[str] = None
    pbs_datastore: Optional[str] = None
    pbs_storage_id: Optional[str] = None
    backup_mode: str
    backup_compress: str
    include_all_disks: bool
    bandwidth_limit: Optional[int] = None
    keep_last: int
    keep_daily: Optional[int] = None
    keep_weekly: Optional[int] = None
    keep_monthly: Optional[int] = None
    schedule: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    is_active: bool
    current_status: str
    last_backup_time: Optional[datetime] = None
    last_backup_id: Optional[str] = None
    last_backup_size: Optional[int] = None
    last_run: Optional[datetime] = None
    last_status: Optional[str] = None
    last_duration: Optional[int] = None
    last_error: Optional[str] = None
    run_count: int
    error_count: int
    notify_on_each_run: bool
    notify_on_failure: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class ClusterPBSBackupJob(BaseModel):
    id: str
    storage: str
    pbs_server: Optional[str] = None
    pbs_datastore: Optional[str] = None
    schedule: Optional[str] = ""
    mode: Optional[str] = "snapshot"
    compress: Optional[str] = "zstd"
    enabled: bool = True
    node: Optional[str] = None
    maxfiles: Optional[int] = None
    vmids: List[int] = Field(default_factory=list)
    vm_count: int = 0
    vm_labels: List[dict] = Field(default_factory=list)
    vm_selection: Optional[str] = None
    managed_by: str = "proxmox"
    dapx_link: Optional[str] = "none"
    dapx_jobs: List[dict] = Field(default_factory=list)
    pbs_node_id: Optional[int] = None
    exec_node_id: Optional[int] = None
    import_hint: Optional[str] = None
    suggested_dapx_kind: Optional[str] = None


# ============== HELPER FUNCTIONS ==============

def job_to_response(job: BackupJob, db: Session) -> BackupJobResponse:
    """Converte BackupJob in response con nomi nodi"""
    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    targets = resolve_vm_targets(job)
    
    return BackupJobResponse(
        id=job.id,
        name=job.name,
        source_node_id=job.source_node_id,
        source_node_name=source_node.name if source_node else None,
        vm_id=job.vm_id,
        vm_type=job.vm_type,
        vm_name=job.vm_name,
        vm_targets=targets,
        vm_count=len(targets),
        vm_summary=job_targets_summary(targets),
        pbs_node_id=job.pbs_node_id,
        pbs_node_name=pbs_node.name if pbs_node else None,
        pbs_datastore=job.pbs_datastore,
        pbs_storage_id=job.pbs_storage_id,
        backup_mode=job.backup_mode,
        backup_compress=job.backup_compress,
        include_all_disks=job.include_all_disks,
        bandwidth_limit=job.bandwidth_limit,
        keep_last=job.keep_last,
        keep_daily=job.keep_daily,
        keep_weekly=job.keep_weekly,
        keep_monthly=job.keep_monthly,
        schedule=job.schedule,
        schedule_config=job.schedule_config,
        is_active=job.is_active,
        current_status=job.current_status,
        last_backup_time=job.last_backup_time,
        last_backup_id=job.last_backup_id,
        last_backup_size=job.last_backup_size,
        last_run=job.last_run,
        last_status=job.last_status,
        last_duration=job.last_duration,
        last_error=job.last_error,
        run_count=job.run_count,
        error_count=job.error_count,
        notify_on_each_run=job.notify_on_each_run,
        notify_on_failure=job.notify_on_failure,
        created_at=job.created_at
    )


# ============== CRUD ENDPOINTS ==============

def _job_visible_to(user: User, job: BackupJob) -> bool:
    """Filtra orizzontale: utenti con `allowed_nodes` ristretto vedono
    solo job che toccano i loro nodi (sorgente o PBS)."""
    if user.allowed_nodes is None:
        return True
    allowed = set(user.allowed_nodes)
    if job.pbs_node_id and job.pbs_node_id in allowed:
        return True
    for t in resolve_vm_targets(job):
        sid = t.get("source_node_id")
        if sid and sid in allowed:
            return True
    if job.source_node_id and job.source_node_id in allowed:
        return True
    return False


@router.get("", response_model=List[BackupJobResponse])
async def list_backup_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista i backup jobs visibili all'utente (filtrati per allowed_nodes)."""
    jobs = db.query(BackupJob).order_by(desc(BackupJob.created_at)).all()
    return [job_to_response(job, db) for job in jobs if _job_visible_to(user, job)]


@router.get("/stats")
async def backup_job_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Statistiche job backup PBS per hub UI."""
    jobs = db.query(BackupJob).all()
    visible = [j for j in jobs if _job_visible_to(user, j)]
    running = sum(
        1 for j in visible if (j.current_status or "").lower() in ("running",)
    )
    failed = sum(
        1 for j in visible if (j.last_status or "").lower() in ("failed", "error")
    )
    scheduled = sum(1 for j in visible if j.is_active and j.schedule)
    return {
        "total": len(visible),
        "active": sum(1 for j in visible if j.is_active),
        "running": running,
        "failed": failed,
        "scheduled": scheduled,
    }


def _cluster_job_visible_to(user: User, item: dict, db: Session) -> bool:
    if user.allowed_nodes is None:
        return True
    allowed = set(user.allowed_nodes)
    for key in ("pbs_node_id", "exec_node_id"):
        nid = item.get(key)
        if nid and nid in allowed:
            return True
    for lbl in item.get("vm_labels") or []:
        pve_name = lbl.get("node")
        if not pve_name:
            continue
        n = _find_node_by_pve_name(db, pve_name)
        if n and n.id in allowed:
            return True
    return False


@router.get("/cluster-jobs", response_model=List[ClusterPBSBackupJob])
async def list_cluster_pbs_backup_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Job vzdump datacenter Proxmox verso storage PBS (non nel DB dapx)."""
    try:
        items = await discover_pve_pbs_backup_jobs(db, user)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        logger.error("Errore discovery backup cluster PBS: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
    visible = [i for i in items if _cluster_job_visible_to(user, i, db)]
    return [ClusterPBSBackupJob(**i) for i in visible]


@router.get("/cluster-jobs/summary")
async def cluster_pbs_backup_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        items = await discover_pve_pbs_backup_jobs(db, user)
        items = [i for i in items if _cluster_job_visible_to(user, i, db)]
    except Exception:
        return {"total": 0, "unlinked": 0, "enabled": 0, "partial": 0}
    unlinked = sum(1 for j in items if j.get("dapx_link") == "none")
    partial = sum(1 for j in items if j.get("dapx_link") == "partial")
    enabled = sum(1 for j in items if j.get("enabled"))
    return {
        "total": len(items),
        "unlinked": unlinked,
        "partial": partial,
        "enabled": enabled,
    }


async def _cluster_pve_node(db: Session) -> Node:
    node = db.query(Node).filter(Node.node_type == NodeType.PVE.value, Node.is_online == True).first()
    if not node:
        node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    if not node:
        raise HTTPException(status_code=500, detail="Nessun nodo PVE disponibile")
    return node


@router.post("/cluster-jobs/{job_id}/run")
async def run_cluster_pbs_backup_job(
    job_id: str,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Avvia manualmente un job backup datacenter Proxmox."""
    node = await _cluster_pve_node(db)
    cmd = f"pvesh create /cluster/backup/{job_id}/run"
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
    )
    if not result.success:
        raise HTTPException(
            status_code=500,
            detail=(result.stderr or result.stdout or "Errore avvio backup cluster")[:500],
        )
    log_audit(db, user.id, "cluster_backup_run", "backup_job", details=f"Run cluster backup {job_id}")
    return {"message": "Backup cluster avviato", "output": (result.stdout or "")[:2000]}


@router.delete("/cluster-jobs/{job_id}")
async def delete_cluster_pbs_backup_job(
    job_id: str,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Elimina un job backup datacenter da Proxmox."""
    node = await _cluster_pve_node(db)
    cmd = f"pvesh delete /cluster/backup/{job_id}"
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
    )
    if not result.success:
        raise HTTPException(
            status_code=500,
            detail=(result.stderr or result.stdout or "Errore eliminazione backup cluster")[:500],
        )
    log_audit(db, user.id, "cluster_backup_delete", "backup_job", details=f"Deleted cluster backup {job_id}")
    return {"message": "Job backup cluster eliminato"}


@router.get("/{job_id}", response_model=BackupJobResponse)
async def get_backup_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene dettagli di un backup job"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    if not _job_visible_to(user, job):
        raise HTTPException(status_code=403, detail="Accesso negato")
    return job_to_response(job, db)


@router.post("", response_model=BackupJobResponse)
async def create_backup_job(
    job_data: BackupJobCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo backup job"""
    targets = normalize_vm_targets(
        vm_targets=[t.model_dump() for t in job_data.vm_targets] if job_data.vm_targets else None,
        source_node_id=job_data.source_node_id,
        vm_id=job_data.vm_id,
        vm_type=job_data.vm_type,
        vm_name=job_data.vm_name,
    )
    if not targets:
        raise HTTPException(status_code=400, detail="Nessuna VM selezionata")

    for t in targets:
        src = db.query(Node).filter(Node.id == t["source_node_id"]).first()
        if not src or src.node_type != NodeType.PVE.value:
            raise HTTPException(
                status_code=400,
                detail=f"Nodo sorgente non valido per VM {t['vm_id']}",
            )

    pbs_node = db.query(Node).filter(Node.id == job_data.pbs_node_id).first()
    if not pbs_node or pbs_node.node_type != NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Nodo PBS non valido")

    cron, cfg = _resolve_schedule_pair(job_data.schedule, job_data.schedule_config)
    first = targets[0]
    display_name = job_data.vm_name
    if not display_name and len(targets) > 1:
        display_name = f"{len(targets)} VM"

    job = BackupJob(
        name=job_data.name,
        source_node_id=first["source_node_id"],
        vm_id=first["vm_id"],
        vm_type=first["vm_type"],
        vm_name=display_name or first.get("vm_name"),
        vm_targets=targets,
        pbs_node_id=job_data.pbs_node_id,
        pbs_datastore=job_data.pbs_datastore or pbs_node.pbs_datastore,
        pbs_storage_id=job_data.pbs_storage_id,
        backup_mode=job_data.backup_mode,
        backup_compress=job_data.backup_compress,
        include_all_disks=job_data.include_all_disks,
        bandwidth_limit=job_data.bandwidth_limit,
        keep_last=job_data.keep_last,
        keep_daily=job_data.keep_daily,
        keep_weekly=job_data.keep_weekly,
        keep_monthly=job_data.keep_monthly,
        schedule=cron,
        schedule_config=cfg,
        is_active=job_data.is_active,
        notify_on_each_run=job_data.notify_on_each_run,
        notify_on_failure=job_data.notify_on_failure,
        created_by=user.id
    )
    
    db.add(job)
    db.commit()
    db.refresh(job)
    
    log_audit(db, user.id, "backup_job_created", "backup_job", 
              resource_id=job.id, details=f"Created backup job: {job.name}")
    
    if job.is_active and job.schedule:
        scheduler_service.update_backup_pbs_schedule(job.id, job.schedule, job.last_run)

    return job_to_response(job, db)


@router.put("/{job_id}", response_model=BackupJobResponse)
async def update_backup_job(
    job_id: int,
    job_data: BackupJobUpdate,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna un backup job"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    update_data = job_data.model_dump(exclude_unset=True)
    if "vm_targets" in update_data and update_data["vm_targets"] is not None:
        targets = normalize_vm_targets(vm_targets=update_data["vm_targets"])
        if not targets:
            raise HTTPException(status_code=400, detail="vm_targets non può essere vuoto")
        for t in targets:
            src = db.query(Node).filter(Node.id == t["source_node_id"]).first()
            if not src or src.node_type != NodeType.PVE.value:
                raise HTTPException(
                    status_code=400,
                    detail=f"Nodo sorgente non valido per VM {t['vm_id']}",
                )
        update_data["vm_targets"] = targets
        first = targets[0]
        update_data["source_node_id"] = first["source_node_id"]
        update_data["vm_id"] = first["vm_id"]
        update_data["vm_type"] = first["vm_type"]
        if len(targets) == 1:
            update_data.setdefault("vm_name", first.get("vm_name"))
        elif "vm_name" not in update_data:
            update_data["vm_name"] = f"{len(targets)} VM"
    if "schedule" in update_data or "schedule_config" in update_data:
        new_cron, new_cfg = _resolve_schedule_pair(
            update_data.get("schedule", job.schedule),
            update_data.get("schedule_config", job.schedule_config),
        )
        update_data["schedule"] = new_cron
        update_data["schedule_config"] = new_cfg
    for key, value in update_data.items():
        setattr(job, key, value)

    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)

    log_audit(db, user.id, "backup_job_updated", "backup_job",
              resource_id=job.id, details=f"Updated backup job: {job.name}")
    
    if job.is_active and job.schedule:
        scheduler_service.update_backup_pbs_schedule(job.id, job.schedule, job.last_run)
    else:
        scheduler_service.remove_backup_pbs_schedule(job.id)

    return job_to_response(job, db)


@router.delete("/{job_id}")
async def delete_backup_job(
    job_id: int,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina un backup job"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    job_name = job.name
    scheduler_service.remove_backup_pbs_schedule(job_id)
    db.delete(job)
    db.commit()
    
    log_audit(db, user.id, "backup_job_deleted", "backup_job",
              resource_id=job_id, details=f"Deleted backup job: {job_name}")
    
    return {"status": "success", "message": f"Backup job '{job_name}' eliminato"}


# ============== EXECUTION ==============

async def execute_backup_task(job_id: int, db_path: str):
    """Task asincrono per eseguire il backup"""
    from database import SessionLocal
    db = SessionLocal()
    
    try:
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        if not job:
            logger.error(f"Backup job {job_id} non trovato")
            return
        
        start_time = datetime.utcnow()
        job.current_status = BackupJobStatus.RUNNING.value
        job.last_run = start_time
        db.commit()

        targets = resolve_vm_targets(job)
        pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
        if not pbs_node:
            raise Exception("Nodo PBS non trovato")

        log = JobLog(
            job_type="backup",
            job_id=job.id,
            node_name=pbs_node.name,
            status="running",
            message=(
                f"Avvio backup {len(targets)} VM ({job.name}) "
                f"verso PBS {pbs_node.name}"
            ),
            started_at=start_time,
        )
        db.add(log)
        db.commit()

        ok_count = 0
        fail_count = 0
        log_lines: list[str] = []
        last_backup_id = None
        last_backup_size = None

        for t in targets:
            source_node = db.query(Node).filter(Node.id == t["source_node_id"]).first()
            if not source_node:
                fail_count += 1
                log_lines.append(f"VM {t['vm_id']}: nodo sorgente {t['source_node_id']} non trovato")
                continue

            storage_id = await _resolve_backup_storage(source_node, job.pbs_storage_id)
            backup_cmd = (
                f"vzdump {t['vm_id']} --storage {storage_id} "
                f"--mode {job.backup_mode} --compress {job.backup_compress}"
            )
            if job.bandwidth_limit:
                backup_cmd += f" --bwlimit {job.bandwidth_limit}"
            if not job.include_all_disks:
                backup_cmd += " --exclude-path /tmp"

            logger.info(
                "Backup job %s VM %s su %s: %s",
                job.id, t["vm_id"], source_node.name, backup_cmd,
            )
            result = await ssh_service.execute(
                hostname=source_node.hostname,
                command=backup_cmd,
                port=source_node.ssh_port,
                username=source_node.ssh_user,
                key_path=source_node.ssh_key_path or "/root/.ssh/id_rsa",
                timeout=7200,
            )
            if result.success:
                ok_count += 1
                log_lines.append(f"VM {t['vm_id']} ({source_node.name}): OK")
                out = result.stdout or ""
                id_match = re.search(r"creating vzdump archive.*?(\S+\.vma)", out)
                if id_match:
                    last_backup_id = id_match.group(1)
                size_match = re.search(r"transferred (\d+(?:\.\d+)?)\s*([KMGT]?B)", out)
                if size_match:
                    size_val = float(size_match.group(1))
                    size_unit = size_match.group(2)
                    multipliers = {
                        "B": 1, "KB": 1024, "MB": 1024**2,
                        "GB": 1024**3, "TB": 1024**4,
                    }
                    last_backup_size = int(size_val * multipliers.get(size_unit, 1))
            else:
                fail_count += 1
                err = (result.stderr or result.stdout or "Errore")[:400]
                log_lines.append(f"VM {t['vm_id']} ({source_node.name}): FAIL — {err}")

        end_time = datetime.utcnow()
        duration = int((end_time - start_time).total_seconds())
        summary = f"{ok_count}/{len(targets)} VM backup OK"
        combined_output = "\n".join(log_lines)

        if fail_count == 0:
            job.current_status = BackupJobStatus.COMPLETED.value
            job.last_status = "success"
            job.last_backup_time = end_time
            job.last_backup_id = last_backup_id
            job.last_backup_size = last_backup_size
            job.run_count += 1
            job.consecutive_failures = 0
            job.last_error = None
            log.status = "success"
            log.message = f"{summary} in {duration}s"
        else:
            job.current_status = BackupJobStatus.FAILED.value
            job.last_status = "failed" if ok_count == 0 else "partial"
            job.error_count += 1
            job.consecutive_failures += 1
            job.last_error = combined_output[:1000]
            log.status = "failed"
            log.message = f"{summary} in {duration}s — vedi dettagli"

        job.last_duration = duration
        log.completed_at = end_time
        log.duration = duration
        log.output = combined_output[:5000] if combined_output else None
        if fail_count:
            log.error = combined_output[:5000]

        db.commit()

        if job.notify_on_each_run or (job.notify_on_failure and fail_count > 0):
            try:
                from services.notification_service import notification_service
                src_label = job_targets_summary(targets)
                await notification_service.send_job_notification(
                    job_type="backup",
                    job_name=job.name,
                    status=job.last_status,
                    source=src_label,
                    destination=f"{pbs_node.name}:{job.pbs_storage_id}",
                    duration=duration,
                    error=job.last_error if fail_count else None,
                    details=f"{summary} — Durata: {duration}s",
                    job_id=job_id,
                    is_scheduled=bool(job.schedule),
                    notify_mode=getattr(job, "notify_mode", None) or "daily",
                    source_node_name=targets[0].get("source_node_id") if targets else None,
                    dest_node_name=pbs_node.name,
                    vm_name=job.vm_name,
                    vm_id=job.vm_id,
                )
            except Exception as e:
                logger.warning(f"Errore invio notifica: {e}")

    except Exception as e:
        logger.exception(f"Errore esecuzione backup job {job_id}")
        if job:
            job.current_status = BackupJobStatus.FAILED.value
            job.last_status = "failed"
            job.last_error = str(e)[:1000]
            job.error_count += 1
            job.consecutive_failures += 1
            db.commit()
    finally:
        db.close()


@router.post("/{job_id}/run")
async def run_backup_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue manualmente un backup job"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    if job.current_status == BackupJobStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="Backup già in esecuzione")
    
    log_audit(db, user.id, "backup_job_manual_run", "backup_job",
              resource_id=job.id, details=f"Manual run: {job.name}")
    
    # Avvia in background
    background_tasks.add_task(execute_backup_task, job_id, "")
    
    return {
        "status": "started",
        "message": f"Backup job '{job.name}' avviato",
        "job_id": job.id
    }


# ============== BACKUP LIST FROM PBS ==============

@router.get("/{job_id}/backups")
async def list_job_backups(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista i backup disponibili per questo job su PBS"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    if not pbs_node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    
    try:
        from services.pbs_service import pbs_service
        backups = await pbs_service.list_vm_backups(
            pbs_node=pbs_node,
            vm_id=job.vm_id,
            vm_type=job.vm_type,
            datastore=job.pbs_datastore
        )
        return {"backups": backups}
    except Exception as e:
        logger.error(f"Errore listing backups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{job_id}/backups/{backup_id}")
async def delete_backup(
    job_id: int,
    backup_id: str,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina un backup specifico da PBS"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    if not pbs_node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    
    try:
        from services.pbs_service import pbs_service
        success = await pbs_service.delete_backup(
            pbs_node=pbs_node,
            backup_id=backup_id,
            datastore=job.pbs_datastore
        )
        
        if success:
            log_audit(db, user.id, "backup_deleted", "backup_job",
                      resource_id=job.id, details=f"Deleted backup: {backup_id}")
            return {"status": "success", "message": "Backup eliminato"}
        else:
            raise HTTPException(status_code=500, detail="Errore eliminazione backup")
    except Exception as e:
        logger.error(f"Errore delete backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _resolve_backup_storage(node: Node, preferred: Optional[str]) -> str:
    """Determina lo storage PBS da usare per il backup."""
    if preferred:
        return preferred

    result = await ssh_service.execute(
        hostname=node.hostname,
        command="pvesm status 2>/dev/null",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )

    if result.success and result.stdout:
        lines = result.stdout.strip().splitlines()
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 3:
                st_name, st_type, st_status = parts[0], parts[1], parts[2]
                if st_type == "pbs" and st_status == "active":
                    return st_name

    return "pbs-backup"

