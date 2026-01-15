"""
Router per gestione PVE Native Replication (pvesr)
Gestisce i job di replica nativa Proxmox (ZFS) nel cluster
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import json

from database import get_db, Node, User, NodeType
from services.ssh_service import ssh_service
from routers.auth import get_current_user, require_operator, log_audit

logger = logging.getLogger(__name__)
router = APIRouter()

#Schemas
class PVEReplicationJob(BaseModel):
    id: str  # Format: vmid-jobid (e.g. 100-0)
    target: str
    vm: Optional[int] = None # Derived from ID
    jobnum: Optional[int] = None # Derived from ID
    schedule: Optional[str] = "*/15"
    rate: Optional[float] = None
    comment: Optional[str] = None
    enabled: bool = True
    source: Optional[str] = None # Node name derived from VM location
    
    # Status fields (populated from status command)
    last_sync: Optional[str] = None
    duration: Optional[float] = None
    fail_count: Optional[int] = None
    last_try: Optional[str] = None
    error: Optional[str] = None
    next_sync: Optional[str] = None

class PVEReplicationCreate(BaseModel):
    vmid: int
    target: str # Target node hostname
    schedule: Optional[str] = "*/15"
    rate: Optional[float] = None # Limit in MB/s
    comment: Optional[str] = None
    enabled: bool = True

class PVEReplicationRun(BaseModel):
    id: str

# Helper Functions
async def _get_cluster_replication_jobs(node: Node) -> List[dict]:
    """Recupera tutti i job di replica dal cluster"""
    # Usiamo un nodo qualsiasi del cluster per interrogare la configurazione globale
    cmd = "pvesh get /cluster/replication --output-format json"
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not result.success:
        raise Exception(f"Errore recupero job replica: {result.stderr}")
        
    return json.loads(result.stdout)

async def _get_replication_status(node: Node) -> List[dict]:
    """Recupera lo stato delle repliche"""
    cmd = "pvesr status --json" # pvesr status gives fuller status info than pvesh get
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not result.success:
        # Fallback to pvesh if pvesr json fails (though pvesr usually supports json)
        return []
        
    return json.loads(result.stdout)

# Endpoints

@router.get("/", response_model=List[PVEReplicationJob])
async def list_replication_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i job di replica PVE (pvesr)"""
    # Trova un nodo PVE online per eseguire il comando
    node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    if not node:
        raise HTTPException(status_code=500, detail="Nessun nodo PVE disponibile per interrogare il cluster")
        
    try:
        # Recupera config e status
        # pvesh restituisce la lista configurata
        config_jobs = await _get_cluster_replication_jobs(node)
        # pvesr status restituisce lo stato corrente (errori, last sync etc)
        # Nota: pvesr status potrebbe mostrare entry per job locale.
        # Meglio usare pvesh per la lista "master" e arricchire.
        
        # Parse and enrich
        jobs = []
        for job in config_jobs:
            # ID format: 100-0
            parts = job.get('id', '').split('-')
            vmid = int(parts[0]) if parts and parts[0].isdigit() else None
            jobnum = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            
            jobs.append(PVEReplicationJob(
                id=job.get('id'),
                target=job.get('target'),
                vm=vmid,
                jobnum=jobnum,
                schedule=job.get('schedule'),
                rate=job.get('rate'),
                comment=job.get('comment'),
                enabled=job.get('enabled', 1) == 1,
                source=job.get('source'), # pvesh output typically includes source node
                # Status fields might be present in config list directly? 
                # pvesh get /cluster/replication output includes 'last_sync', 'fail_count' etc often.
                last_sync=str(job.get('last_sync', '')),
                duration=job.get('duration'),
                fail_count=job.get('fail_count'),
                error=job.get('error'),
                next_sync=str(job.get('next_sync', ''))
            ))
            
        return jobs
        
    except Exception as e:
        logger.error(f"Errore listing replication jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/", response_model=dict)
async def create_replication_job(
    job: PVEReplicationCreate,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo job di replica PVE nativa"""
    if job.vmid < 100:
        raise HTTPException(status_code=400, detail="VMID non valido")
        
    # Trova nodo sorgente della VM? 
    # Per creare il job dobbiamo sapere dove gira la VM? 
    # 'pvesh create' può essere lanciato da qualsiasi nodo del cluster, 
    # ma pvesr richiede che la VM esista.
    
    # Trova un nodo PVE qualsiasi per lanciare il comando
    node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    if not node:
        raise HTTPException(status_code=500, detail="Nessun nodo PVE disponibile")

    # Costruzione comando
    # ID formato: VMID-N. Dobbiamo trovare N libero?
    # pvesr create-local-job lo fa in automatico?
    
    # Verifichiamo prima i job esistenti per quel VMID per trovare prossimo ID
    try:
        current_jobs = await _get_cluster_replication_jobs(node)
        existing_ids = [j['id'] for j in current_jobs if j.get('guest', j.get('vm')) == job.vmid or j['id'].startswith(f"{job.vmid}-")]
        
        next_num = 0
        used_nums = []
        for jid in existing_ids:
            try:
                used_nums.append(int(jid.split('-')[1]))
            except: pass
        
        while next_num in used_nums:
            next_num += 1
            
        job_id = f"{job.vmid}-{next_num}"
        
        # pvesh create /cluster/replication --id ...
        cmd_parts = [
            "pvesh", "create", "/cluster/replication",
            "--id", job_id,
            "--target", job.target,
            "--schedule", f"'{job.schedule}'"
        ]
        
        if job.rate:
            cmd_parts.extend(["--rate", str(job.rate)])
        if job.comment:
            cmd_parts.extend(["--comment", f"'{job.comment}'"])
        if not job.enabled:
            cmd_parts.extend(["--disable", "1"])
            
        cmd = " ".join(cmd_parts)
        
        result = await ssh_service.execute(
            hostname=node.hostname,
            command=cmd,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
        
        if not result.success:
            raise Exception(f"Errore creazione job: {result.stderr}")
            
        log_audit(db, user.id, "pve_replication_create", "replication", details=f"Created job {job_id} -> {job.target}")
        
        return {"message": "Job creato", "id": job_id}
        
    except Exception as e:
        logger.error(f"Errore creazione replication job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{job_id}")
async def delete_replication_job(
    job_id: str,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina un job di replica"""
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
            key_path=node.ssh_key_path
        )
        
        if not result.success:
            raise Exception(f"Errore eliminazione job: {result.stderr}")
            
        log_audit(db, user.id, "pve_replication_delete", "replication", details=f"Deleted job {job_id}")
        return {"message": "Job eliminato"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{job_id}/run")
async def run_replication_job_now(
    job_id: str,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue immediatamente un job di replica"""
    # pvesr run -id ID deve essere eseguito sul nodo SORGENTE della VM?
    # Sì, 'pvesr run' gira localmente.
    
    # 1. Trova il job per capire la VM
    node = db.query(Node).filter(Node.node_type == NodeType.PVE.value).first()
    try:
        jobs = await _get_cluster_replication_jobs(node)
        target_job = next((j for j in jobs if j['id'] == job_id), None)
        if not target_job:
            raise HTTPException(status_code=404, detail="Job non trovato")
            
        vmid = int(job_id.split('-')[0])
        
        # 2. Trova dove gira la VM (Source Node)
        # Usiamo il servizio proxmox per trovare il nodo
        from services.proxmox_service import proxmox_service
        # Dobbiamo iterare sui nodi o chiedere al cluster?
        # 'pvesh get /cluster/resources --type vm' gives node info
        
        cmd_res = "pvesh get /cluster/resources --type vm --output-format json"
        res_result = await ssh_service.execute(node.hostname, cmd_res, node.ssh_port, node.ssh_user, node.ssh_key_path)
        
        source_node_name = None
        if res_result.success:
            vms = json.loads(res_result.stdout)
            vm = next((v for v in vms if v.get('vmid') == vmid), None)
            if vm:
                source_node_name = vm.get('node')
        
        if not source_node_name:
            # Fallback: prova a dedurre da 'source' field se presente nel job
            if 'source' in target_job:
                source_node_name = target_job['source']
            else:
                raise Exception("Impossibile determinare il nodo sorgente della VM")
        
        # 3. Esegui comando sul nodo sorgente
        source_node_obj = db.query(Node).filter(Node.hostname == source_node_name).first() # Hostname might differ from PVE node name?
        # In PVE, node name is usually hostname-ish logic.
        # But we store 'name' and 'hostname' (ip/fqdn).
        # We need to find the Node DB object by name
        if not source_node_obj:
             source_node_obj = db.query(Node).filter(Node.name == source_node_name).first()
             
        if not source_node_obj:
            raise Exception(f"Nodo sorgente '{source_node_name}' non trovato nel DB")
            
        cmd_run = f"pvesr run --id {job_id}"
        run_result = await ssh_service.execute(
            hostname=source_node_obj.hostname,
            command=cmd_run,
            port=source_node_obj.ssh_port,
            username=source_node_obj.ssh_user,
            key_path=source_node_obj.ssh_key_path,
            timeout=300 # pvesr run can take time
        )
        
        if not run_result.success:
            raise Exception(f"Errore esecuzione: {run_result.stderr}")
            
        return {"message": "Replica avviata", "output": run_result.stdout}
        
    except Exception as e:
        logger.error(f"Errore run replication: {e}")
        raise HTTPException(status_code=500, detail=str(e))
