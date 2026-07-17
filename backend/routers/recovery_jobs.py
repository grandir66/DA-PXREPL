"""
Router per gestione Recovery Jobs (replica basata su PBS)
Permette di configurare e gestire job di backup/restore automatici
"""

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio
import logging
import re
import json

from database import (
    get_db, Node, RecoveryJob, JobLog, User,
    NodeType, RecoveryJobStatus, VirtualMachine
)
from services.pbs_service import pbs_service
from services.schedule_helpers import resolve_schedule_pair
from services.proxmox_service import proxmox_service
from services.ssh_service import ssh_service
from routers.auth import get_current_user, require_operator, require_admin, log_audit
from routers.deps import assert_node_access, check_node_access, filter_nodes_for_user
from services.recovery_job_schemas import (
    BackupInfo,
    DirectRestoreRequest,
    PBSNodeInfo,
    RecoveryJobCreate,
    RecoveryJobResponse,
    RecoveryJobUpdate,
)
from services.recovery_job_helpers import (
    assert_recovery_job_access,
    build_vm_name_map,
    require_recovery_node as _require_recovery_node,
)
from services.recovery_job_execution import execute_recovery_job_task
from services.scheduler import scheduler_service
from services.recovery_pbs_inventory import resolve_pbs_inventory_context

logger = logging.getLogger(__name__)
router = APIRouter()



def _resolve_schedule_pair(schedule: Optional[str], schedule_config: Optional[Dict[str, Any]]):
    try:
        return resolve_schedule_pair(schedule, schedule_config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"schedule_config non valido: {e}")


# Helper


# ============== Schemas ==============



# ============== Helper Functions ==============




# ============== Endpoints ==============

@router.get("/", response_model=List[RecoveryJobResponse])
async def list_recovery_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i recovery jobs con durate delle ultime fasi"""
    jobs = db.query(RecoveryJob).all()
    if user.role != "admin" and user.allowed_nodes is not None:
        allowed = set(user.allowed_nodes)
        jobs = [
            j for j in jobs
            if j.source_node_id in allowed and j.dest_node_id in allowed and j.pbs_node_id in allowed
        ]
    
    # Cache dei nomi dei nodi per efficienza
    node_names = {n.id: n.name for n in db.query(Node).all()}
    
    # Cache dei nomi VM (asincrono)
    try:
        vm_map = await build_vm_name_map(db)
    except Exception as e:
        logger.warning(f"Failed to build VM map: {e}")
        vm_map = {}

    # Aggiungi durate delle ultime fasi per ogni job
    result = []
    for job in jobs:
        # Recupera info VM aggiornate dal nodo sorgente
        current_vm_name = job.vm_name
        lookup_key = f"{job.source_node_id}-{job.vm_id}"
        
        if lookup_key in vm_map:
             current_vm_name = vm_map[lookup_key]["name"]
             
        job_dict = {
            **job.__dict__,
            "vm_name": current_vm_name,
            "source_node_name": node_names.get(job.source_node_id, f"Node {job.source_node_id}"),
            "pbs_node_name": node_names.get(job.pbs_node_id, f"Node {job.pbs_node_id}"),
            "dest_node_name": node_names.get(job.dest_node_id, f"Node {job.dest_node_id}"),
            "last_backup_duration": None,
            "last_restore_duration": None
        }
        
        # Recupera ultimo log backup
        last_backup_log = db.query(JobLog).filter(
            JobLog.job_id == job.id,
            JobLog.job_type == "backup"
        ).order_by(JobLog.started_at.desc()).first()
        
        if last_backup_log and last_backup_log.duration:
            job_dict["last_backup_duration"] = last_backup_log.duration
        
        # Recupera ultimo log restore
        last_restore_log = db.query(JobLog).filter(
            JobLog.job_id == job.id,
            JobLog.job_type == "restore"
        ).order_by(JobLog.started_at.desc()).first()
        
        if last_restore_log and last_restore_log.duration:
            job_dict["last_restore_duration"] = last_restore_log.duration
        
        result.append(RecoveryJobResponse(**job_dict))
    
    return result


@router.post("/", response_model=RecoveryJobResponse)
async def create_recovery_job(
    job_data: RecoveryJobCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo recovery job"""
    
    # Verifica nodi esistenti
    source_node = db.query(Node).filter(Node.id == job_data.source_node_id).first()
    pbs_node = db.query(Node).filter(Node.id == job_data.pbs_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job_data.dest_node_id).first()
    
    if not source_node:
        raise HTTPException(status_code=404, detail="Nodo sorgente non trovato")
    if not pbs_node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    if not dest_node:
        raise HTTPException(status_code=404, detail="Nodo destinazione non trovato")
    
    # Verifica che il nodo PBS sia effettivamente un PBS
    if pbs_node.node_type != NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Il nodo PBS specificato non è di tipo PBS")
    
    # Verifica accesso ai nodi
    if not check_node_access(user, source_node) or not check_node_access(user, dest_node):
        raise HTTPException(status_code=403, detail="Accesso negato ai nodi specificati")
    if not check_node_access(user, pbs_node):
        raise HTTPException(status_code=403, detail="Accesso negato al nodo PBS")
    
    # Crea il job: allinea schedule (cron) e schedule_config (JSON struct)
    payload = job_data.model_dump()
    cron, cfg = _resolve_schedule_pair(payload.get("schedule"), payload.get("schedule_config"))
    payload["schedule"] = cron
    payload["schedule_config"] = cfg
    job = RecoveryJob(
        **payload,
        created_by=user.id
    )
    db.add(job)
    
    log_audit(
        db, user.id, "recovery_job_created", "recovery_job",
        details=f"Created recovery job: {job_data.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(job)
    if job.is_active and job.schedule:
        scheduler_service.update_recovery_pbs_schedule(job.id, job.schedule, job.last_run)
    return job


# ============== PBS Node Endpoints ==============



@router.get("/pbs-nodes/", response_model=List[PBSNodeInfo])
async def list_pbs_nodes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i nodi PBS configurati"""
    pbs_nodes = db.query(Node).filter(Node.node_type == NodeType.PBS.value).all()
    pbs_nodes = filter_nodes_for_user(user, pbs_nodes)

    async def _node_info(node: Node) -> PBSNodeInfo:
        datastores: List[str] = []
        try:
            datastores = await pbs_service.list_datastore_names(node)
        except Exception as e:
            logger.warning(f"Impossibile elencare datastore PBS per {node.name}: {e}")

        return PBSNodeInfo(
            id=node.id,
            name=node.name,
            hostname=node.hostname,
            pbs_available=node.pbs_available,
            pbs_version=node.pbs_version,
            pbs_datastore=node.pbs_datastore,
            datastores=datastores,
        )

    return await asyncio.gather(*[_node_info(n) for n in pbs_nodes])


@router.post("/pbs-nodes/{node_id}/test")
async def test_pbs_node(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Testa la connessione a un nodo PBS"""
    node = db.query(Node).filter(
        Node.id == node_id,
        Node.node_type == NodeType.PBS.value
    ).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    assert_node_access(user, node)
    
    # Test connessione SSH
    ssh_ok, ssh_msg = await ssh_service.test_connection(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not ssh_ok:
        return {
            "success": False,
            "ssh": {"success": False, "message": ssh_msg},
            "pbs": {"success": False, "message": "SSH non disponibile"}
        }
    
    # Test PBS server
    pbs_ok, pbs_version = await pbs_service.check_pbs_server(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Aggiorna stato nodo
    node.is_online = ssh_ok
    node.pbs_available = pbs_ok
    node.pbs_version = pbs_version
    node.last_check = datetime.utcnow()
    db.commit()
    
    # Lista datastore se disponibile
    datastores = []
    if pbs_ok:
        datastores = await pbs_service.list_datastores(
            hostname=node.hostname,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
    
    return {
        "success": ssh_ok and pbs_ok,
        "ssh": {"success": ssh_ok, "message": ssh_msg},
        "pbs": {
            "success": pbs_ok,
            "version": pbs_version,
            "datastores": [ds.get("name") for ds in datastores] if datastores else []
        }
    }


@router.get("/pbs-nodes/{node_id}/backups")
async def list_pbs_backups(
    node_id: int,
    vm_id: Optional[int] = None,
    datastore: Optional[str] = None,
    pve_node_id: Optional[int] = None,
    pbs_storage: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lista i backup disponibili su un nodo PBS.
    
    Preferisce sempre pvesh via nodo PVE (include notes con nome VM).
    Fallback a proxmox-backup-client se non c'è nodo PVE disponibile.
    """
    node, ds, pve_node, storage_name = await resolve_pbs_inventory_context(
        db, user, node_id, datastore, pve_node_id, pbs_storage
    )

    try:
        backups = await pbs_service.list_inventory_backups(
            pbs_node=node,
            datastore=ds,
            vm_id=vm_id,
            pve_node=pve_node,
            pbs_storage=storage_name,
        )
    except Exception as e:
        logger.error(f"Errore listing backups PBS: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "datastore": ds,
        "backups": backups,
        "count": len(backups)
    }


@router.get("/pbs-nodes/{node_id}/backups/vms")
async def list_pbs_backup_vms(
    node_id: int,
    datastore: Optional[str] = None,
    pve_node_id: Optional[int] = None,
    pbs_storage: Optional[str] = None,
    force_refresh: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Riepilogo VM con conteggio backup (lazy load — senza catena date)."""
    node, ds, pve_node, storage_name = await resolve_pbs_inventory_context(
        db, user, node_id, datastore, pve_node_id, pbs_storage
    )

    try:
        vms = await pbs_service.list_inventory_vm_summaries(
            pbs_node=node,
            datastore=ds,
            pve_node=pve_node,
            pbs_storage=storage_name,
            force_refresh=force_refresh,
        )
    except Exception as e:
        logger.error(f"Errore summary PBS: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    total_versions = sum(v.get("backup_count", 0) for v in vms)
    return {
        "datastore": ds,
        "vms": vms,
        "vm_count": len(vms),
        "total_versions": total_versions,
    }


@router.get("/pbs-nodes/{node_id}/backups/vms/{vm_id}")
async def list_pbs_backup_vm_versions(
    node_id: int,
    vm_id: int,
    datastore: Optional[str] = None,
    pve_node_id: Optional[int] = None,
    pbs_storage: Optional[str] = None,
    force_refresh: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Catena date backup per una singola VM (caricata on-demand)."""
    node, ds, pve_node, storage_name = await resolve_pbs_inventory_context(
        db, user, node_id, datastore, pve_node_id, pbs_storage
    )

    try:
        versions = await pbs_service.list_inventory_vm_versions(
            pbs_node=node,
            datastore=ds,
            vm_id=vm_id,
            pve_node=pve_node,
            pbs_storage=storage_name,
            force_refresh=force_refresh,
        )
    except Exception as e:
        logger.error(f"Errore versioni PBS vm {vm_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "datastore": ds,
        "vmid": vm_id,
        "versions": versions,
        "count": len(versions),
    }


# ============== Direct Restore Endpoint ==============



@router.post("/restore")
async def direct_restore(
    request: DirectRestoreRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Esegue un restore diretto da un backup PBS esistente.
    Questo endpoint permette di ripristinare qualsiasi backup presente nel PBS,
    anche quelli non creati da questo applicativo.
    """
    # Verifica nodo PBS
    pbs_node = db.query(Node).filter(
        Node.id == request.pbs_node_id,
        Node.node_type == NodeType.PBS.value
    ).first()
    
    if not pbs_node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    
    # Verifica nodo destinazione
    dest_node = db.query(Node).filter(
        Node.id == request.dest_node_id,
        Node.node_type == NodeType.PVE.value
    ).first()
    
    if not dest_node:
        raise HTTPException(status_code=404, detail="Nodo PVE destinazione non trovato")
    assert_node_access(user, pbs_node)
    assert_node_access(user, dest_node)
    
    # Estrai VMID dal backup_id se non specificato
    vmid = request.dest_vmid
    if not vmid:
        # Prova a estrarre il VMID dal backup_id (formato: vm/100/2024-01-01...)
        import re
        match = re.search(r'(vm|ct)/(\d+)/', request.backup_id)
        if match:
            vmid = int(match.group(2))
        else:
            raise HTTPException(status_code=400, detail="VMID non specificato e non estraibile dal backup_id")
    
    # Log dell'operazione
    log_audit(db, user.id, "restore_started", "restore", 
              resource_id=vmid, details=f"Restore da PBS {pbs_node.name} verso {dest_node.name}")
    
    # Crea entry nel job_logs
    from database import JobLog
    from datetime import datetime
    
    restore_log = JobLog(
        job_type="restore",
        node_name=dest_node.name,
        status="running",
        message=f"Restore VM {vmid} da PBS {pbs_node.name} (backup: {request.backup_id[:50]}...)",
        started_at=datetime.utcnow()
    )
    db.add(restore_log)
    db.commit()
    db.refresh(restore_log)
    
    # Esegui il restore
    datastore = pbs_node.pbs_datastore or "datastore1"
    storage = request.dest_storage
    
    start_time = datetime.utcnow()
    result = await pbs_service.run_restore(
        dest_node_hostname=dest_node.hostname,
        vm_id=vmid,
        pbs_hostname=pbs_node.hostname,
        datastore=datastore,
        backup_id=request.backup_id,
        pbs_user=pbs_node.pbs_username or f"{pbs_node.ssh_user}@pam",
        pbs_password=pbs_node.pbs_password,
        pbs_fingerprint=pbs_node.pbs_fingerprint,
        dest_vm_id=vmid,
        dest_storage=storage,
        vm_type=request.vm_type,
        start_vm=False,
        unique=True,
        overwrite=True,
        dest_node_port=dest_node.ssh_port,
        dest_node_user=dest_node.ssh_user,
        dest_node_key=dest_node.ssh_key_path or "/root/.ssh/id_rsa"
    )
    
    end_time = datetime.utcnow()
    duration = int((end_time - start_time).total_seconds())
    
    if not result.get("success"):
        # Aggiorna log con errore
        restore_log.status = "failed"
        restore_log.error = result.get("error", "Errore sconosciuto")
        restore_log.message = f"Restore VM {vmid} fallito: {result.get('error', 'Errore')[:100]}"
        restore_log.completed_at = end_time
        restore_log.duration = duration
        db.commit()
        
        log_audit(db, user.id, "restore_failed", "restore",
                  resource_id=vmid, details=result.get("error", "Errore sconosciuto"))
        raise HTTPException(status_code=500, detail=result.get("error", "Errore durante il restore"))
    
    # Aggiorna log con successo
    restore_log.status = "success"
    restore_log.message = f"Restore VM {vmid} completato su {dest_node.name} (storage: {storage or 'default'})"
    restore_log.completed_at = end_time
    restore_log.duration = duration
    db.commit()
    
    log_audit(db, user.id, "restore_completed", "restore",
              resource_id=vmid, details=f"Restore completato su {dest_node.name} come VM {vmid}")
    
    return {
        "success": True,
        "message": f"Restore completato con successo",
        "vmid": vmid,
        "node": dest_node.name,
        "duration": duration
    }


# ============== Storage & VMID Endpoints ==============

@router.get("/node/{node_id}/storages")
async def get_node_storages(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene la lista degli storage disponibili su un nodo PVE.
    Utile per selezionare lo storage di destinazione per il restore.
    """
    node = _require_recovery_node(db, user, node_id)
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    # Esegui comando per ottenere storage
    result = await ssh_service.execute(
        hostname=node.hostname,
        command="pvesm status --output-format json 2>/dev/null || pvesm status",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    storages = []
    
    if result.success:
        import json
        try:
            # Prova a parsare come JSON
            storage_list = json.loads(result.stdout)
            for s in storage_list:
                storages.append({
                    "name": s.get("storage"),
                    "type": s.get("type"),
                    "content": s.get("content", ""),
                    "active": s.get("active", 1) == 1,
                    "enabled": s.get("enabled", 1) == 1,
                    "used": s.get("used", 0),
                    "total": s.get("total", 0),
                    "avail": s.get("avail", 0)
                })
        except json.JSONDecodeError:
            # Fallback: parse output testuale
            # Format: Name Type Status Total Used Available %
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                for line in lines[1:]:  # Skip header
                    parts = line.split()
                    if len(parts) >= 2:
                        # Parse storage info
                        name = parts[0]
                        stype = parts[1] if len(parts) > 1 else "unknown"
                        active = parts[2] == "active" if len(parts) > 2 else True
                        total = int(parts[3]) * 1024 if len(parts) > 3 and parts[3].isdigit() else 0
                        used = int(parts[4]) * 1024 if len(parts) > 4 and parts[4].isdigit() else 0
                        avail = int(parts[5]) * 1024 if len(parts) > 5 and parts[5].isdigit() else 0
                        
                        storages.append({
                            "name": name,
                            "type": stype,
                            "active": active,
                            "total": total,
                            "used": used,
                            "avail": avail,
                            "content": ""
                        })
    
    # Filtra storage che supportano images/rootdir (utili per VM)
    vm_storages = [s for s in storages if 
                   'images' in s.get('content', '') or 
                   'rootdir' in s.get('content', '') or
                   s.get('type') in ['zfspool', 'lvmthin', 'lvm', 'dir', 'nfs', 'cifs', 'btrfs']]
    
    # Filtra storage PBS (tipo pbs, content backup)
    pbs_storages = [s for s in storages if s.get('type') == 'pbs']
    
    return {
        "node": node.name,
        "storages": storages,
        "vm_storages": vm_storages,  # Storage adatti per VM
        "pbs_storages": pbs_storages  # Storage PBS configurati
    }


@router.get("/node/{node_id}/pbs-storages")
async def get_node_pbs_storages(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene la lista degli storage PBS configurati su un nodo PVE.
    Questi sono gli storage che possono essere usati per backup verso PBS.
    """
    node = _require_recovery_node(db, user, node_id)
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    # Ottieni configurazione storage PBS
    result = await ssh_service.execute(
        hostname=node.hostname,
        command="""
pvesm status --output-format json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
pbs = [s for s in data if s.get('type') == 'pbs']
print(json.dumps(pbs))
" 2>/dev/null || pvesm status | grep ' pbs ' | awk '{print $1}'
""",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    pbs_storages = []
    
    if result.success and result.stdout.strip():
        import json
        try:
            pbs_storages = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Fallback: lista semplice di nomi
            for name in result.stdout.strip().split('\n'):
                if name:
                    pbs_storages.append({
                        "name": name.strip(),
                        "type": "pbs",
                        "active": True
                    })
    
    # Per ogni storage PBS, ottieni i dettagli di configurazione
    for storage in pbs_storages:
        storage_name = storage.get("storage") or storage.get("name")
        if storage_name:
            detail_result = await ssh_service.execute(
                hostname=node.hostname,
                command=f"pvesm config {storage_name} 2>/dev/null",
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            if detail_result.success:
                # Parse config
                for line in detail_result.stdout.strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        storage[key.strip()] = value.strip()
    
    return {
        "node": node.name,
        "pbs_storages": pbs_storages
    }


@router.get("/node/{node_id}/check-vmid/{vmid}")
async def check_vmid_available(
    node_id: int,
    vmid: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verifica se un VMID è disponibile su un nodo PVE.
    Ritorna info sulla VM esistente se il VMID è già in uso.
    """
    node = _require_recovery_node(db, user, node_id)
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    # Verifica QEMU VM
    qm_result = await ssh_service.execute(
        hostname=node.hostname,
        command=f"qm status {vmid} 2>/dev/null && qm config {vmid} 2>/dev/null | grep -E '^name:'",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if qm_result.success and "status:" in qm_result.stdout:
        # VMID in uso da una VM QEMU
        lines = qm_result.stdout.strip().split('\n')
        status_line = lines[0] if lines else ""
        name_line = next((l for l in lines if l.startswith("name:")), "")
        vm_name = name_line.replace("name:", "").strip() if name_line else f"VM {vmid}"
        
        status = "running" if "running" in status_line else "stopped"
        
        return {
            "available": False,
            "vmid": vmid,
            "in_use_by": {
                "type": "qemu",
                "name": vm_name,
                "status": status
            },
            "message": f"VMID {vmid} già in uso da VM '{vm_name}' ({status})"
        }
    
    # Verifica LXC Container
    pct_result = await ssh_service.execute(
        hostname=node.hostname,
        command=f"pct status {vmid} 2>/dev/null && pct config {vmid} 2>/dev/null | grep -E '^hostname:'",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if pct_result.success and "status:" in pct_result.stdout:
        # VMID in uso da un container LXC
        lines = pct_result.stdout.strip().split('\n')
        status_line = lines[0] if lines else ""
        name_line = next((l for l in lines if l.startswith("hostname:")), "")
        ct_name = name_line.replace("hostname:", "").strip() if name_line else f"CT {vmid}"
        
        status = "running" if "running" in status_line else "stopped"
        
        return {
            "available": False,
            "vmid": vmid,
            "in_use_by": {
                "type": "lxc",
                "name": ct_name,
                "status": status
            },
            "message": f"VMID {vmid} già in uso da Container '{ct_name}' ({status})"
        }
    
    # VMID disponibile
    return {
        "available": True,
        "vmid": vmid,
        "in_use_by": None,
        "message": f"VMID {vmid} disponibile"
    }


@router.get("/node/{node_id}/next-vmid")
async def get_next_available_vmid(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene il prossimo VMID disponibile su un nodo PVE.
    """
    node = _require_recovery_node(db, user, node_id)
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    # Usa pvesh per ottenere il prossimo VMID
    result = await ssh_service.execute(
        hostname=node.hostname,
        command="pvesh get /cluster/nextid 2>/dev/null || echo '100'",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    next_vmid = 100
    if result.success:
        try:
            next_vmid = int(result.stdout.strip())
        except ValueError:
            pass
    
    return {
        "node": node.name,
        "next_vmid": next_vmid
    }


@router.get("/node/{node_id}/vms")
async def get_node_vms_for_recovery(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene la lista delle VM/CT su un nodo PVE.
    Include VMID, nome, tipo e stato.
    """
    node = _require_recovery_node(db, user, node_id)
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    vms = []
    
    # Lista QEMU VMs
    qm_result = await ssh_service.execute(
        hostname=node.hostname,
        command="qm list 2>/dev/null | tail -n +2",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if qm_result.success:
        for line in qm_result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 3:
                    vms.append({
                        "vmid": int(parts[0]),
                        "name": parts[1],
                        "status": parts[2],
                        "type": "qemu"
                    })
    
    # Lista LXC Containers
    pct_result = await ssh_service.execute(
        hostname=node.hostname,
        command="pct list 2>/dev/null | tail -n +2",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if pct_result.success:
        for line in pct_result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    vms.append({
                        "vmid": int(parts[0]),
                        "status": parts[1],
                        "name": parts[3] if len(parts) >= 4 else f"CT{parts[0]}",
                        "type": "lxc"
                    })
    
    # Ordina per VMID
    vms.sort(key=lambda x: x["vmid"])
    
    return {
        "node": node.name,
        "vms": vms,
        "count": len(vms)
    }


@router.get("/{job_id}", response_model=RecoveryJobResponse)
async def get_recovery_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene un recovery job specifico"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    assert_recovery_job_access(user, job, db)
    return job


@router.put("/{job_id}", response_model=RecoveryJobResponse)
async def update_recovery_job(
    job_id: int,
    job_data: RecoveryJobUpdate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna un recovery job"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    assert_recovery_job_access(user, job, db)
    
    update_data = job_data.model_dump(exclude_unset=True)
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

    log_audit(
        db, user.id, "recovery_job_updated", "recovery_job",
        resource_id=job_id,
        details=f"Updated recovery job: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(job)
    if job.is_active and job.schedule:
        scheduler_service.update_recovery_pbs_schedule(job.id, job.schedule, job.last_run)
    else:
        scheduler_service.remove_recovery_pbs_schedule(job.id)
    return job


@router.delete("/{job_id}")
async def delete_recovery_job(
    job_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Elimina un recovery job"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    assert_recovery_job_access(user, job, db)
    
    job_name = job.name
    scheduler_service.remove_recovery_pbs_schedule(job_id)
    db.delete(job)
    
    log_audit(
        db, user.id, "recovery_job_deleted", "recovery_job",
        resource_id=job_id,
        details=f"Deleted recovery job: {job_name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    return {"message": "Recovery job eliminato"}


@router.post("/{job_id}/run")
async def run_recovery_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue manualmente un recovery job"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    assert_recovery_job_access(user, job, db)
    
    # Verifica che non sia già in esecuzione
    if job.current_status in [
        RecoveryJobStatus.BACKING_UP.value,
        RecoveryJobStatus.RESTORING.value,
        RecoveryJobStatus.REGISTERING.value
    ]:
        raise HTTPException(status_code=400, detail="Job già in esecuzione")
    
    log_audit(
        db, user.id, "recovery_job_manual_run", "recovery_job",
        resource_id=job_id,
        details=f"Manual run: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    # Avvia il job in background
    background_tasks.add_task(execute_recovery_job_task, job_id, user.id)
    
    return {
        "message": f"Recovery job {job.name} avviato",
        "job_id": job_id
    }


@router.post("/{job_id}/backup-only")
async def run_backup_only(
    job_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue solo la fase di backup di un recovery job"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    assert_recovery_job_access(user, job, db)
    
    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    
    if not source_node or not pbs_node:
        raise HTTPException(status_code=404, detail="Nodi non trovati")
    
    datastore = job.pbs_datastore or pbs_node.pbs_datastore or "datastore1"
    
    # Esegui backup
    result = await pbs_service.run_backup(
        source_node_hostname=source_node.hostname,
        vm_id=job.vm_id,
        pbs_hostname=pbs_node.hostname,
        datastore=datastore,
        pbs_user=pbs_node.pbs_username or f"{pbs_node.ssh_user}@pam",
        pbs_password=pbs_node.pbs_password,
        pbs_fingerprint=pbs_node.pbs_fingerprint,
        pbs_storage_id=job.pbs_storage_id,  # Usa storage esistente se specificato
        vm_type=job.vm_type,
        mode=job.backup_mode,
        compress=job.backup_compress,
        source_node_port=source_node.ssh_port,
        source_node_user=source_node.ssh_user,
        source_node_key=source_node.ssh_key_path
    )
    
    # Aggiorna job
    if result["success"]:
        job.last_backup_time = datetime.utcnow()
        job.last_backup_id = result.get("backup_id")
        db.commit()
    
    return result


@router.post("/{job_id}/restore-only")
async def run_restore_only(
    job_id: int,
    backup_id: Optional[str] = None,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue solo la fase di restore di un recovery job (usa ultimo backup disponibile o backup_id specifico)"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    assert_recovery_job_access(user, job, db)
    
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    
    if not pbs_node or not dest_node:
        raise HTTPException(status_code=404, detail="Nodi non trovati")
    
    datastore = job.pbs_datastore or pbs_node.pbs_datastore or "datastore1"
    
    # Esegui restore
    result = await pbs_service.run_restore(
        dest_node_hostname=dest_node.hostname,
        vm_id=job.vm_id,
        pbs_hostname=pbs_node.hostname,
        datastore=datastore,
        backup_id=backup_id or job.last_backup_id,
        pbs_user=pbs_node.pbs_username or f"{pbs_node.ssh_user}@pam",
        pbs_password=pbs_node.pbs_password,
        pbs_fingerprint=pbs_node.pbs_fingerprint,
        dest_vm_id=job.dest_vm_id,
        dest_storage=job.dest_storage,
        vm_type=job.vm_type,
        start_vm=job.restore_start_vm,
        unique=job.restore_unique,
        overwrite=job.overwrite_existing,
        dest_node_port=dest_node.ssh_port,
        dest_node_user=dest_node.ssh_user,
        dest_node_key=dest_node.ssh_key_path
    )
    
    # Aggiorna job
    if result["success"]:
        job.last_restore_time = datetime.utcnow()
        db.commit()
    
    return result


