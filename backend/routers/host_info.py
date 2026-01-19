"""
Router per informazioni dettagliate host Proxmox
Espone dati hardware, storage, network raccolti da host_info_service
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import logging
import json
import re

from database import get_db, Node, User
from services.host_info_service import host_info_service
from services.proxmox_service import proxmox_service
from services.ssh_service import ssh_service
from routers.auth import get_current_user
from routers.nodes import check_node_access

router = APIRouter()
logger = logging.getLogger(__name__)


# ============== Schemas ==============

class HostDetailsResponse(BaseModel):
    """Risposta con dettagli host"""
    node_id: int
    node_name: str
    hostname: str
    timestamp: str
    proxmox_version: Optional[str] = None
    kernel_version: Optional[str] = None
    uptime_seconds: Optional[int] = None
    cpu: Dict[str, Any] = {}
    memory: Dict[str, Any] = {}
    storage: List[Dict[str, Any]] = []
    network: List[Dict[str, Any]] = []
    temperature: Dict[str, Any] = {}
    license: Dict[str, Any] = {}


class VMFullDetailsResponse(BaseModel):
    """Risposta con dettagli completi VM"""
    vmid: int
    name: str
    node_id: int
    node_name: str
    vm_type: str
    status: str
    config: Dict[str, Any] = {}
    runtime: Dict[str, Any] = {}
    disks: List[Dict[str, Any]] = []
    networks: List[Dict[str, Any]] = []
    ip_addresses: Dict[str, List[str]] = {}
    snapshots: Dict[str, Any] = {}
    agent: Dict[str, Any] = {}
    # Campi aggiuntivi opzionali
    bios: Optional[str] = None
    ostype: Optional[str] = None
    boot: Optional[str] = None
    agent_enabled: Optional[bool] = None
    primary_bridge: Optional[str] = None
    primary_ip: Optional[str] = None
    tags: Optional[str] = None
    
    class Config:
        extra = "allow"  # Permette campi aggiuntivi


class DashboardOverviewResponse(BaseModel):
    """Risposta overview dashboard"""
    total_nodes: int
    online_nodes: int
    total_vms: int
    running_vms: int
    total_storage_gb: float
    used_storage_gb: float
    total_memory_gb: float
    used_memory_gb: float
    total_cpu_cores: int
    nodes_summary: List[Dict[str, Any]] = []
    job_stats: Dict[str, Any] = {}
    recent_logs: List[Dict[str, Any]] = []


# ============== Endpoints ==============

@router.get("/nodes/{node_id}/host-details", response_model=HostDetailsResponse)
async def get_node_host_details(
    node_id: int,
    include_hardware: bool = True,
    include_storage: bool = True,
    include_network: bool = True,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene dettagli completi dell'host Proxmox.
    Include hardware, storage, network, temperatura, licenza.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    if node.node_type != "pve":
        raise HTTPException(status_code=400, detail="Endpoint disponibile solo per nodi PVE")
    
    # Raccolta dati host
    # Raccolta dati host (da cache o refresh)
    host_details = await host_info_service.get_host_details(node_id=node.id)
    
    if not host_details:
         # Se cache vuota, prova fetch diretto (fallback)
         host_details = await host_info_service.update_host_details(node.id)
    
    if not host_details:
        raise HTTPException(status_code=500, detail="Impossibile recuperare dettagli host")
    
    # Aggiungi node_id e node_name
    host_details["node_id"] = node_id
    host_details["node_name"] = node.name
    
    return HostDetailsResponse(**host_details)


@router.get("/nodes/{node_id}/vms/{vmid}/full-details", response_model=VMFullDetailsResponse)
async def get_vm_full_details(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene dettagli completi di una VM.
    Include config, runtime stats, dischi, network, IP, snapshot, agent.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    if node.node_type != "pve":
        raise HTTPException(status_code=400, detail="Endpoint disponibile solo per nodi PVE")
    
    try:
        # Ottieni dettagli completi VM usando il nuovo metodo
        vm_details = await proxmox_service.get_vm_full_details(
            hostname=node.hostname,
            node_name=node.name,
            vmid=vmid,
            vm_type=vm_type,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
        
        # Verifica che la VM esista (se status è unknown e non ci sono dati, probabilmente non esiste)
        if vm_details.get("status") == "unknown" and not vm_details.get("config"):
            # Verifica esistenza con lista VM
            vms = await proxmox_service.get_all_guests(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            vm_found = next((vm for vm in vms if vm.get("vmid") == vmid and vm.get("type") == vm_type), None)
            if not vm_found:
                raise HTTPException(status_code=404, detail="VM non trovata")
        
        # Aggiungi node_id e node_name
        vm_details["node_id"] = node_id
        vm_details["node_name"] = node.name
        
        try:
            return VMFullDetailsResponse(**vm_details)
        except Exception as e:
            logger.error(f"Errore serializzazione VM details per VM {vmid}: {e}", exc_info=True)
            logger.error(f"Campi disponibili: {list(vm_details.keys())}")
            # Prova a restituire comunque i dati, anche se non perfettamente validati
            # Converti in dict per evitare problemi di serializzazione
            return vm_details
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Errore recupero dettagli VM {vmid} su nodo {node_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Errore recupero dettagli VM: {str(e)}")


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene overview aggregata per dashboard.
    Include statistiche totali e summary nodi.
    """
    # Ottieni nodi accessibili
    from routers.nodes import filter_nodes_for_user
    nodes_query = db.query(Node).filter(Node.is_active == True)
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    total_nodes = len(nodes)
    online_nodes = sum(1 for n in nodes if n.is_online)
    
    # Aggrega dati da tutti i nodi
    total_vms = 0
    running_vms = 0
    total_storage_gb = 0.0
    used_storage_gb = 0.0
    total_memory_gb = 0.0
    used_memory_gb = 0.0
    total_cpu_cores = 0
    nodes_summary = []
    
    # Traccia storage condivisi già contati (per evitare duplicati)
    counted_shared_storage = set()
    
    for node in nodes:
        if not node.is_online:
            continue
        
        # Supportiamo anche PBS (node_type="pbs")
        
        try:
            # Raccolta dati host (solo summary, senza dettagli completi)
            # Raccolta dati host (da cache)
            host_details = await host_info_service.get_host_details(node_id=node.id)
            if not host_details:
                # Prova update veloce se manca
                host_details = await host_info_service.update_host_details(node.id)
            
            if not host_details:
                continue
            
            # Aggrega storage (deduplicando storage condivisi)
            node_storage_total = 0.0
            node_storage_used = 0.0
            for storage in host_details.get("storage", []):
                storage_name = storage.get("name", "")
                is_shared = storage.get("shared", False)
                
                # Per il singolo nodo, conta tutto
                if storage.get("total_gb"):
                    node_storage_total += storage["total_gb"]
                if storage.get("used_gb"):
                    node_storage_used += storage["used_gb"]
                
                # Per il totale globale, conta shared solo una volta
                if is_shared:
                    if storage_name not in counted_shared_storage:
                        counted_shared_storage.add(storage_name)
                        if storage.get("total_gb"):
                            total_storage_gb += storage["total_gb"]
                        if storage.get("used_gb"):
                            used_storage_gb += storage["used_gb"]
                else:
                    # Storage locale: conta sempre
                    if storage.get("total_gb"):
                        total_storage_gb += storage["total_gb"]
                    if storage.get("used_gb"):
                        used_storage_gb += storage["used_gb"]
            
            # Aggrega memory
            if host_details.get("memory", {}).get("total_gb"):
                total_memory_gb += host_details["memory"]["total_gb"]
            if host_details.get("memory", {}).get("used_gb"):
                used_memory_gb += host_details["memory"]["used_gb"]
            
            # Aggrega CPU
            if host_details.get("cpu", {}).get("cores"):
                total_cpu_cores += host_details["cpu"]["cores"]
            
            # Conta VM
            vms = await proxmox_service.get_all_guests(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            total_vms += len(vms)
            running_vms += sum(1 for vm in vms if vm.get("status", "").lower() == "running")
            
            # Summary nodo (mostra tutto lo storage del nodo, non deduplicato)
            nodes_summary.append({
                "node_id": node.id,
                "node_name": node.name,
                "hostname": node.hostname,
                "is_online": node.is_online,
                "cpu_cores": host_details.get("cpu", {}).get("cores", 0),
                "memory_total_gb": host_details.get("memory", {}).get("total_gb", 0),
                "memory_used_gb": host_details.get("memory", {}).get("used_gb", 0),
                "storage_total_gb": round(node_storage_total, 2),
                "storage_used_gb": round(node_storage_used, 2),
                "vm_count": len(vms),
                "running_vm_count": sum(1 for vm in vms if vm.get("status", "").lower() == "running"),
                "temperature_highest_c": host_details.get("temperature", {}).get("highest_c"),
                "proxmox_version": host_details.get("proxmox_version")
            })
        except Exception as e:
            # Skip nodi con errori
            logger.error(f"Errore raccolta dati nodo {node.name}: {e}")
            continue
    
    # Ottieni statistiche job
    from database import SyncJob, BackupJob, RecoveryJob, MigrationJob
    sync_jobs = db.query(SyncJob).filter(SyncJob.is_active == True).all()
    backup_jobs = db.query(BackupJob).filter(BackupJob.is_active == True).all()
    recovery_jobs = db.query(RecoveryJob).filter(RecoveryJob.is_active == True).all()
    migration_jobs = db.query(MigrationJob).filter(MigrationJob.is_active == True).all()
    
    job_stats = {
        "replica_zfs": sum(1 for j in sync_jobs if j.sync_method == "syncoid"),
        "replica_btrfs": sum(1 for j in sync_jobs if j.sync_method == "btrfs_send"),
        "backup_pbs": len(backup_jobs),
        "replica_pbs": len(recovery_jobs),
        "migration": len(migration_jobs),
        "total": len(sync_jobs) + len(backup_jobs) + len(recovery_jobs) + len(migration_jobs)
    }
    
    # Ottieni log recenti
    from database import JobLog
    recent_logs_query = db.query(JobLog).order_by(JobLog.started_at.desc()).limit(10)
    recent_logs = []
    for log in recent_logs_query.all():
        recent_logs.append({
            "id": log.id,
            "job_type": log.job_type,
            "job_name": log.job_name,
            "status": log.status,
            "started_at": log.started_at.isoformat() if log.started_at else None,
            "duration": log.duration,
            "node_name": log.node_name,
            "message": log.message[:200] if log.message else None
        })
    
    return DashboardOverviewResponse(
        total_nodes=total_nodes,
        online_nodes=online_nodes,
        total_vms=total_vms,
        running_vms=running_vms,
        total_storage_gb=round(total_storage_gb, 2),
        used_storage_gb=round(used_storage_gb, 2),
        total_memory_gb=round(total_memory_gb, 2),
        used_memory_gb=round(used_memory_gb, 2),
        total_cpu_cores=total_cpu_cores,
        nodes_summary=nodes_summary,
        job_stats=job_stats,
        recent_logs=recent_logs
    )


@router.get("/dashboard/nodes", response_model=List[Dict[str, Any]])
async def get_dashboard_nodes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene lista nodi con summary per dashboard.
    Restituisce dati nel formato compatibile con il frontend.
    """
    from routers.nodes import filter_nodes_for_user
    nodes_query = db.query(Node).filter(Node.is_active == True)
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    nodes_list = []
    for node in nodes:
        node_summary = {
            "id": node.id,
            "name": node.name,
            "hostname": node.hostname,
            "node_type": node.node_type,
            "is_online": node.is_online,
            "last_check": node.last_check.isoformat() if node.last_check else None,
            # Inizializza campi con valori di default
            "proxmox_version": None,
            "cpu": {},
            "memory": {},
            "storage": [],
            "temperature": {},
            "storage_total_gb": 0,
            "storage_used_gb": 0,
            "vm_count": 0,
            "running_vm_count": 0,
            "temperature_highest_c": None,
            "sanoid_installed": node.sanoid_installed,
            "sanoid_version": node.sanoid_version,
            # PBS specific
            "pbs_datastore": node.pbs_datastore,
            "pbs_username": node.pbs_username,
            "pbs_fingerprint": node.pbs_fingerprint
        }
        
        # Se online, aggiungi summary dati (supporta PVE e PBS)
        if node.is_online:
            try:
                host_details = await host_info_service.get_host_details(node_id=node.id)
                
                if not host_details:
                    host_details = {}
                # Conta VM
                vms = await proxmox_service.get_all_guests(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path
                )
                
                # Calcola storage totale e usato
                storage_list = host_details.get("storage", [])
                storage_total_gb = sum((s.get("total_gb") or 0) for s in storage_list)
                storage_used_gb = sum((s.get("used_gb") or 0) for s in storage_list)
                
                # Aggiorna summary con dati raccolti
                cpu_data = host_details.get("cpu", {})
                memory_data = host_details.get("memory", {})
                temperature_data = host_details.get("temperature", {})
                
                node_summary.update({
                    "proxmox_version": host_details.get("proxmox_version"),
                    "cpu": cpu_data,
                    "memory": memory_data,
                    "storage": host_details.get("storage", []),
                    "temperature": temperature_data,
                    # Network topology data
                    "network": host_details.get("network", []),
                    "guests": host_details.get("guests", []),
                    # Full host_info for detailed modal
                    "host_info": host_details,
                    # Campi aggiuntivi per compatibilità frontend
                    "storage_total_gb": round(storage_total_gb, 2) if storage_total_gb > 0 else 0,
                    "storage_used_gb": round(storage_used_gb, 2) if storage_used_gb > 0 else 0,
                    "vm_count": len(vms) if vms else 0,
                    "running_vm_count": sum(1 for vm in vms if vm.get("status", "").lower() == "running") if vms else 0,
                    "temperature_highest_c": temperature_data.get("highest_c") if temperature_data else None
                })
                
                logger.debug(f"Nodo {node.name}: {len(vms) if vms else 0} VM totali, {node_summary['running_vm_count']} running, storage: {storage_total_gb}GB")
            except Exception as e:
                # In caso di errore, mantieni i valori di default (None)
                logger.error(f"Errore raccolta dati per nodo {node.id} ({node.name}): {e}", exc_info=True)
        
        nodes_list.append(node_summary)
    
    return nodes_list


@router.get("/nodes/{node_id}/metrics")
async def get_node_metrics(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene metriche di performance in tempo reale per un nodo.
    Include CPU usage, RAM usage, Network I/O, Disk I/O.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    if node.node_type != "pve":
        raise HTTPException(status_code=400, detail="Endpoint disponibile solo per nodi PVE")
    
    if not node.is_online:
        raise HTTPException(status_code=400, detail="Nodo non online")
    
    metrics = await host_info_service.get_node_metrics(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    metrics["node_id"] = node_id
    metrics["node_name"] = node.name
    
    return metrics


@router.get("/dashboard/nodes-metrics")
async def get_all_nodes_metrics(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene metriche di performance per tutti i nodi online.
    Ottimizzato per dashboard con chiamate parallele.
    """
    from routers.nodes import filter_nodes_for_user
    nodes_query = db.query(Node).filter(Node.is_active == True, Node.node_type == "pve", Node.is_online == True)
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    import asyncio
    
    async def get_metrics_for_node(node):
        try:
            metrics = await host_info_service.get_node_metrics(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            metrics["node_id"] = node.id
            metrics["node_name"] = node.name
            return metrics
        except Exception as e:
            logger.error(f"Errore metriche nodo {node.name}: {e}")
            return {
                "node_id": node.id,
                "node_name": node.name,
                "error": str(e)
            }
    
    # Raccogli metriche in parallelo
    tasks = [get_metrics_for_node(node) for node in nodes]
    all_metrics = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filtra errori
    result = []
    for metrics in all_metrics:
        if isinstance(metrics, Exception):
            continue
        if "error" not in metrics:
            result.append(metrics)
    
    return result


@router.get("/dashboard/job-stats")
async def get_dashboard_job_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene statistiche job per tipo (replica ZFS, replica BTRFS, backup PBS, replica PBS, migrazione).
    """
    from database import SyncJob, BackupJob, RecoveryJob, MigrationJob
    
    # Filtra job accessibili all'utente
    sync_jobs = db.query(SyncJob).filter(SyncJob.is_active == True).all()
    backup_jobs = db.query(BackupJob).filter(BackupJob.is_active == True).all()
    recovery_jobs = db.query(RecoveryJob).filter(RecoveryJob.is_active == True).all()
    migration_jobs = db.query(MigrationJob).filter(MigrationJob.is_active == True).all()
    
    # Conta per tipo
    stats = {
        "replica_zfs": 0,
        "replica_btrfs": 0,
        "backup_pbs": len(backup_jobs),
        "replica_pbs": len(recovery_jobs),
        "migration": len(migration_jobs),
        "total": 0
    }
    
    # Conta replica ZFS e BTRFS
    for job in sync_jobs:
        if job.sync_method == "syncoid":
            stats["replica_zfs"] += 1
        elif job.sync_method == "btrfs_send":
            stats["replica_btrfs"] += 1
    
    stats["total"] = stats["replica_zfs"] + stats["replica_btrfs"] + stats["backup_pbs"] + stats["replica_pbs"] + stats["migration"]
    
    # Statistiche per stato
    stats["by_status"] = {
        "success": 0,
        "failed": 0,
        "running": 0,
        "pending": 0
    }
    
    # Conta stati per tipo job
    for job in sync_jobs:
        if job.last_status == "success":
            stats["by_status"]["success"] += 1
        elif job.last_status == "failed":
            stats["by_status"]["failed"] += 1
        elif job.last_status == "running":
            stats["by_status"]["running"] += 1
        else:
            stats["by_status"]["pending"] += 1
    
    for job in backup_jobs + recovery_jobs + migration_jobs:
        status = getattr(job, 'last_status', None) or "pending"
        if status == "success":
            stats["by_status"]["success"] += 1
        elif status == "failed":
            stats["by_status"]["failed"] += 1
        elif status == "running":
            stats["by_status"]["running"] += 1
        else:
            stats["by_status"]["pending"] += 1
    
    return stats


# Dashboard VM Endpoint (Moved from vms.py)
@router.get("/dashboard/vms")
async def get_all_dashboard_vms(
    force_refresh: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene lista di tutte le VM con dettagli.
    
    - Se force_refresh=False (default): usa cache dal DB (veloce, < 100ms)
    - Se force_refresh=True: richiede dati real-time via SSH/API (lento, ~5-30s)
    
    La cache viene aggiornata in background dal scheduler ogni minuto.
    """
    from services.proxmox_service import proxmox_service
    from services.ssh_service import ssh_service
    from routers.nodes import filter_nodes_for_user
    from database import VirtualMachine
    
    nodes_query = db.query(Node).filter(Node.is_active == True, Node.is_online == True)
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    # Mappa node_id -> node per lookup
    node_map = {n.id: n for n in nodes}
    node_name_map = {n.name: n for n in nodes}
    for n in nodes:
        node_name_map[n.hostname] = n  # Anche per hostname
    
    # ========= FAST PATH: Use DB Cache =========
    if not force_refresh:
        node_ids = [n.id for n in nodes]
        cached_vms = db.query(VirtualMachine).filter(VirtualMachine.node_id.in_(node_ids)).all()
        
        # Se abbiamo dati in cache, restituiscili
        if cached_vms:
            result = []
            for vm in cached_vms:
                node = node_map.get(vm.node_id)
                result.append({
                    "vmid": vm.vmid,
                    "name": vm.name,
                    "type": vm.type,
                    "status": vm.status,
                    "node": node.name if node else "unknown",
                    "node_id": vm.node_id,
                    "maxmem": vm.memory or 0,
                    "maxcpu": vm.cpus or 0,
                    "uptime": vm.uptime or 0,
                    "net0_ip": None,  # IP non cachato per velocità
                    "cpu": 0,  # Usage non disponibile in cache
                    "mem": 0,
                    "disk": 0,
                    "maxdisk": 0,
                    "_cached": True,
                    "_cache_time": vm.last_updated.isoformat() if vm.last_updated else None
                })
            logger.debug(f"Returning {len(result)} VMs from cache")
            return result
        
        # Se cache vuota, fallback a real-time
        logger.warning("VM cache empty, falling back to real-time fetch")
    
    # ========= SLOW PATH: Real-time SSH fetch =========
    import asyncio
    
    async def get_node_vms_resources(node):
        try:
            return await proxmox_service.get_cluster_resources(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
        except Exception as e:
            logger.error(f"Errore recupero risorse da {node.hostname}: {e}")
            return []

    tasks = [get_node_vms_resources(n) for n in nodes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_vms = {}
    
    # Map results
    for i, res in enumerate(results):
        if isinstance(res, list):
            for item in res:
                # Filter for qemu and lxc
                if item.get("type") in ["qemu", "lxc"]:
                    # Chiave univoca: node/vmid
                    key = f"{item.get('node')}/{item.get('vmid')}"
                    
                    # Normalizza campi
                    item["node_id"] = nodes[i].id
                    item["net0_ip"] = None  # Default
                    
                    # Mappatura ID host corretto
                    host_node_name = item.get("node")
                    if host_node_name and host_node_name in node_name_map:
                        item["node_id"] = node_name_map[host_node_name].id
                    
                    all_vms[key] = item
    
    # Fase 2: Fetch IP per VM running via QEMU agent (in parallelo) - Solo se force_refresh
    async def fetch_vm_ip(vm_key: str, vm_data: dict, node: Node) -> tuple:
        """Recupera IP via agent per una singola VM"""
        try:
            vmid = vm_data.get("vmid")
            vm_type = vm_data.get("type", "qemu")
            node_name = vm_data.get("node", node.name)
            
            # Comando agent per ottenere IP
            cmd = f"pvesh get /nodes/{node_name}/{vm_type}/{vmid}/agent/network-get-interfaces --output-format json 2>/dev/null"
            result = await ssh_service.execute(
                hostname=node.hostname,
                command=cmd,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            if result.success and result.stdout.strip():
                try:
                    data = json.loads(result.stdout)
                    interfaces = data.get("result", []) if isinstance(data, dict) else data
                    
                    # Estrai primo IP IPv4 non-localhost
                    for iface in interfaces if isinstance(interfaces, list) else []:
                        for ip_entry in iface.get("ip-addresses", []) or iface.get("ip_addresses", []):
                            if isinstance(ip_entry, dict):
                                ip = ip_entry.get("ip-address") or ip_entry.get("ip") or ""
                                if ip and ip not in ["127.0.0.1", "::1"] and ":" not in ip:
                                    return (vm_key, ip)
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.debug(f"IP fetch failed for VM {vm_data.get('vmid')}: {e}")
        
        return (vm_key, None)
    
    # Prepara task IP fetch solo per VM running
    ip_fetch_tasks = []
    for vm_key, vm_data in all_vms.items():
        if vm_data.get("status") == "running":
            host_node_name = vm_data.get("node")
            node = node_name_map.get(host_node_name)
            if node:
                ip_fetch_tasks.append(fetch_vm_ip(vm_key, vm_data, node))
    
    # Esegui fetch IP in parallelo (max 10 concurrent)
    if ip_fetch_tasks:
        # Usa semaphore per limitare concorrenza
        semaphore = asyncio.Semaphore(10)
        
        async def limited_fetch(task_coro):
            async with semaphore:
                return await task_coro
        
        ip_results = await asyncio.gather(
            *[limited_fetch(t) for t in ip_fetch_tasks],
            return_exceptions=True
        )
        
        # Aggiorna VMs con IP trovati
        for result in ip_results:
            if isinstance(result, tuple) and len(result) == 2:
                vm_key, ip = result
                if ip and vm_key in all_vms:
                    all_vms[vm_key]["net0_ip"] = ip
    
    return list(all_vms.values())


