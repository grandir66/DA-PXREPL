"""
Router per gestione nodi Proxmox (PVE e PBS)
Con autenticazione e autorizzazione
"""

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel

from database import get_db, Node, Dataset, User, AuditLog, StorageType, NodeType, VirtualMachine, SessionLocal
from services.ssh_service import ssh_service
from services.sanoid_service import sanoid_service
from services.proxmox_service import proxmox_service
from services.btrfs_service import btrfs_service
from services.pbs_service import pbs_service
from services.ssh_key_service import ssh_key_service
from services.cache_service import cache_service
from routers.auth import get_current_user, require_operator, require_admin, log_audit
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ============== Schemas ==============

from pathlib import Path

class NodeCreate(BaseModel):
    name: str
    hostname: str
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_key_path: str = str(Path.home() / ".ssh" / "id_rsa")
    # Node type: pve (Proxmox VE) or pbs (Proxmox Backup Server)
    node_type: str = "pve"
    proxmox_api_url: Optional[str] = None
    proxmox_api_token: Optional[str] = None
    proxmox_verify_ssl: bool = False
    is_auth_node: bool = False
    # PBS specific
    pbs_datastore: Optional[str] = None
    pbs_fingerprint: Optional[str] = None
    pbs_username: Optional[str] = "root@pam"
    pbs_password: Optional[str] = None
    # Storage type: zfs, btrfs (only for PVE nodes)
    storage_type: str = "zfs"
    # BTRFS config
    btrfs_mount: Optional[str] = None
    btrfs_snapshot_dir: Optional[str] = None
    notes: Optional[str] = None
    # SSH setup - password per distribuzione automatica chiave
    ssh_password: Optional[str] = None
    auto_distribute_key: bool = True


class NodeUpdate(BaseModel):
    name: Optional[str] = None
    hostname: Optional[str] = None
    ssh_port: Optional[int] = None
    ssh_user: Optional[str] = None
    ssh_key_path: Optional[str] = None
    node_type: Optional[str] = None
    proxmox_api_url: Optional[str] = None
    proxmox_api_token: Optional[str] = None
    proxmox_verify_ssl: Optional[bool] = None
    is_auth_node: Optional[bool] = None
    is_active: Optional[bool] = None
    # PBS specific
    pbs_datastore: Optional[str] = None
    pbs_fingerprint: Optional[str] = None
    pbs_username: Optional[str] = None
    pbs_password: Optional[str] = None
    # Storage type
    storage_type: Optional[str] = None
    btrfs_mount: Optional[str] = None
    btrfs_snapshot_dir: Optional[str] = None
    notes: Optional[str] = None


class NodeResponse(BaseModel):
    id: int
    name: str
    hostname: str
    ssh_port: int
    ssh_user: str
    ssh_key_path: str
    # Node type
    node_type: Optional[str] = "pve"
    proxmox_api_url: Optional[str] = None
    proxmox_verify_ssl: bool = False
    is_auth_node: bool = False
    # PBS specific
    pbs_datastore: Optional[str] = None
    pbs_fingerprint: Optional[str] = None
    pbs_username: Optional[str] = None
    pbs_available: Optional[bool] = False
    pbs_version: Optional[str] = None
    # Storage
    storage_type: Optional[str] = "zfs"
    btrfs_mount: Optional[str] = None
    btrfs_snapshot_dir: Optional[str] = None
    btrfs_available: Optional[bool] = False
    btrfs_version: Optional[str] = None
    # Status
    is_active: bool = True
    is_online: bool = False
    last_check: Optional[datetime] = None
    sanoid_installed: bool = False
    sanoid_version: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    notes: Optional[str] = None
    # Advanced Host Info
    host_info: Optional[Dict[str, Any]] = None
    host_info_updated_at: Optional[datetime] = None
    
    # Calculated fields for UI
    vm_count: Optional[int] = 0
    running_vm_count: Optional[int] = 0
    storage_total_gb: Optional[float] = 0.0
    storage_used_gb: Optional[float] = 0.0
    cpu: Optional[Dict[str, Any]] = None
    memory: Optional[Dict[str, Any]] = None
    temperature_highest_c: Optional[float] = None
    proxmox_version: Optional[str] = None
    
    # SSH setup info (solo per creazione)
    ssh_key_setup: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True


class DatasetResponse(BaseModel):
    id: int
    node_id: int
    name: str
    mountpoint: Optional[str]
    used: Optional[str]
    available: Optional[str]
    snapshot_count: int
    sanoid_enabled: bool
    sanoid_template: str
    hourly: int
    daily: int
    weekly: int
    monthly: int
    yearly: int
    autosnap: bool
    autoprune: bool
    last_snapshot: Optional[datetime]
    
    class Config:
        from_attributes = True


# ============== Helper Functions ==============

def check_node_access(user: User, node: Node) -> bool:
    """Verifica se l'utente ha accesso al nodo"""
    if user.role == "admin":
        return True
    if user.allowed_nodes is None:
        return True
    return node.id in user.allowed_nodes


def filter_nodes_for_user(db: Session, user: User, nodes_query):
    """Filtra i nodi in base ai permessi dell'utente"""
    if user.role == "admin" or user.allowed_nodes is None:
        return nodes_query
    return nodes_query.filter(Node.id.in_(user.allowed_nodes))

def enhance_node_response(node: Node, db: Session) -> dict:
    """Arricchisce la risposta con dati calcolati"""
    # Converti in dict
    resp = {c.name: getattr(node, c.name) for c in node.__table__.columns}
    
    # Calcola VM counts usando la tabella cached VirtualMachine
    try:
        vm_query = db.query(VirtualMachine).filter(VirtualMachine.node_id == node.id)
        resp["vm_count"] = vm_query.count()
        resp["running_vm_count"] = vm_query.filter(VirtualMachine.status == "running").count()
    except Exception:
        resp["vm_count"] = 0
        resp["running_vm_count"] = 0
        
    # Estrai info da host_info se presente
    if node.host_info:
        info = node.host_info
        resp["host_info"] = info
        resp["cpu"] = info.get("cpu")
        resp["memory"] = info.get("memory")
        
        # Storage è una lista: somma i valori
        storage_list = info.get("storage", [])
        if isinstance(storage_list, list) and storage_list:
            resp["storage_total_gb"] = sum(s.get("total_gb", 0) or 0 for s in storage_list)
            resp["storage_used_gb"] = sum(s.get("used_gb", 0) or 0 for s in storage_list)
        else:
            resp["storage_total_gb"] = 0
            resp["storage_used_gb"] = 0
        
        # Temperature (potrebbe essere in temperature o hardware)
        temp_data = info.get("temperature", {})
        if temp_data and isinstance(temp_data, dict):
            resp["temperature_highest_c"] = temp_data.get("highest")
        
        # Proxmox version è alla radice di host_info
        if not resp.get("proxmox_version"):
            resp["proxmox_version"] = info.get("proxmox_version")
    
    return resp

# ============== Endpoints ==============

@router.get("/", response_model=List[NodeResponse])
async def list_nodes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i nodi accessibili all'utente"""
    query = db.query(Node)
    query = filter_nodes_for_user(db, user, query)
    nodes = query.all()
    
    # Arricchisci risposta
    return [enhance_node_response(n, db) for n in nodes]


@router.post("/", response_model=NodeResponse)
async def create_node(
    node: NodeCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo nodo (richiede ruolo operator o admin)"""
    
    # Verifica unicità nome
    existing = db.query(Node).filter(Node.name == node.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Nome nodo già esistente")
    
    # Estrai campi non-model
    ssh_password = node.ssh_password
    auto_distribute_key = node.auto_distribute_key
    
    # Crea dict senza campi extra (model_dump per pydantic v2)
    node_data = node.model_dump(exclude={'ssh_password', 'auto_distribute_key'})
    
    db_node = Node(**node_data)
    db.add(db_node)
    
    log_audit(
        db, user.id, "node_created", "node",
        details=f"Created node: {node.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(db_node)
    
    # Distribuzione automatica chiave SSH
    ssh_key_result = None
    if auto_distribute_key:
        try:
            # Verifica se esiste una chiave locale
            key_info = ssh_key_service.get_key_info()
            if not key_info.exists:
                # Genera chiave se non esiste
                success, msg = ssh_key_service.generate_key()
                if not success:
                    logger.warning(f"Impossibile generare chiave SSH: {msg}")
            
            # Prima prova senza password (potrebbe già avere la chiave)
            result = await ssh_key_service.distribute_key_to_host(
                hostname=db_node.hostname,
                port=db_node.ssh_port,
                username=db_node.ssh_user,
                password=None
            )
            
            if result.success or result.already_present:
                ssh_key_result = {
                    "success": True,
                    "message": result.message,
                    "already_present": result.already_present
                }
            elif ssh_password:
                # Riprova con password
                result = await ssh_key_service.distribute_key_to_host(
                    hostname=db_node.hostname,
                    port=db_node.ssh_port,
                    username=db_node.ssh_user,
                    password=ssh_password
                )
                ssh_key_result = {
                    "success": result.success,
                    "message": result.message,
                    "already_present": result.already_present
                }
            else:
                ssh_key_result = {
                    "success": False,
                    "message": "Chiave SSH non distribuita. Fornire la password root per configurare l'accesso SSH.",
                    "needs_password": True
                }
            
            # Test connessione
            if ssh_key_result.get("success") or ssh_key_result.get("already_present"):
                test_success, test_msg = await ssh_key_service.test_key_auth(
                    hostname=db_node.hostname,
                    port=db_node.ssh_port,
                    username=db_node.ssh_user
                )
                ssh_key_result["connection_test"] = {
                    "success": test_success,
                    "message": test_msg
                }
                
                # Aggiorna stato online del nodo
                db_node.is_online = test_success
                db.commit()
                
        except Exception as e:
            logger.error(f"Errore distribuzione chiave SSH a {node.hostname}: {e}")
            ssh_key_result = {
                "success": False,
                "message": str(e),
                "needs_password": True
            }
    
    # Costruisci risposta
    response = {
        "id": db_node.id,
        "name": db_node.name,
        "hostname": db_node.hostname,
        "ssh_port": db_node.ssh_port,
        "ssh_user": db_node.ssh_user,
        "ssh_key_path": db_node.ssh_key_path,
        "node_type": db_node.node_type,
        "storage_type": db_node.storage_type,
        "is_online": db_node.is_online,
        "is_active": db_node.is_active,
        "ssh_key_setup": ssh_key_result
    }
    
    return response


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene un nodo specifico"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    return node


@router.put("/{node_id}", response_model=NodeResponse)
async def update_node(
    node_id: int,
    update: NodeUpdate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(node, key, value)
    
    # Auto-detect PBS fingerprint if missing but we have credentials and it's a PBS node
    if node.node_type == NodeType.PBS.value and node.pbs_username and not node.pbs_fingerprint:
        try:
             # Fetch fingerprint
             fingerprint = await pbs_service.get_fingerprint(
                 hostname=node.hostname,
                 port=node.ssh_port,
                 username=node.ssh_user,
                 key_path=node.ssh_key_path
             )
             if fingerprint:
                 node.pbs_fingerprint = fingerprint
                 logger.info(f"Auto-detected PBS fingerprint for {node.name}: {fingerprint}")
        except Exception as e:
            logger.warning(f"Failed to auto-detect fingerprint for {node.name}: {e}")

    node.updated_at = datetime.utcnow()
    
    log_audit(
        db, user.id, "node_updated", "node",
        resource_id=node_id,
        details=f"Updated node: {node.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(node)
    return node


@router.delete("/{node_id}")
async def delete_node(
    node_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Elimina un nodo (solo admin)"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    node_name = node.name
    db.delete(node)
    
    log_audit(
        db, user.id, "node_deleted", "node",
        resource_id=node_id,
        details=f"Deleted node: {node_name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    return {"message": "Nodo eliminato"}


@router.post("/{node_id}/test")
async def test_node_connection(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Testa la connessione a un nodo e verifica ZFS/BTRFS/PBS disponibili"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    success, message = await ssh_service.test_connection(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Aggiorna stato
    node.is_online = success
    node.last_check = datetime.utcnow()
    
    btrfs_info = None
    pbs_info = None
    
    if success:
        # Se è un nodo PBS
        if node.node_type == NodeType.PBS.value:
            pbs_ok, pbs_version = await pbs_service.check_pbs_server(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            node.pbs_available = pbs_ok
            node.pbs_version = pbs_version if pbs_ok else None
            
            # Lista datastore se disponibile
            datastores = []
            if pbs_ok:
                ds_list = await pbs_service.list_datastores(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path
                )
                datastores = [ds.get("name") for ds in ds_list] if ds_list else []
            
            pbs_info = {
                "available": pbs_ok,
                "version": pbs_version if pbs_ok else None,
                "datastores": datastores
            }
        else:
            # Nodo PVE - Check sanoid (ZFS)
            sanoid_ok, version = await ssh_service.check_sanoid_installed(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            node.sanoid_installed = sanoid_ok
            node.sanoid_version = version
            
            # Check BTRFS se il tipo di storage è btrfs o se vogliamo verificare la disponibilità
            if node.storage_type == "btrfs" or node.btrfs_mount:
                btrfs_ok, btrfs_version = await btrfs_service.check_btrfs_available(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path
                )
                node.btrfs_available = btrfs_ok
                node.btrfs_version = btrfs_version if btrfs_ok else None
                
                # Verifica mount point BTRFS se configurato
                if btrfs_ok and node.btrfs_mount:
                    mount_ok, mount_info = await btrfs_service.check_btrfs_mount(
                        hostname=node.hostname,
                        mount_point=node.btrfs_mount,
                        port=node.ssh_port,
                        username=node.ssh_user,
                        key_path=node.ssh_key_path
                    )
                    btrfs_info = {
                        "available": btrfs_ok,
                        "version": btrfs_version if btrfs_ok else None,
                        "mount_ok": mount_ok,
                        "mount_info": mount_info
                    }
                else:
                    btrfs_info = {
                        "available": btrfs_ok,
                        "version": btrfs_version if btrfs_ok else None
                    }
            
            # Verifica anche PBS client per nodi PVE (per poter fare backup)
            pbs_client_ok, pbs_client_version = await pbs_service.check_pbs_available(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            if pbs_client_ok:
                pbs_info = {
                    "client_available": True,
                    "client_version": pbs_client_version
                }
    
    db.commit()
    
    result = {
        "success": success,
        "message": message,
        "node_type": node.node_type,
        "storage_type": node.storage_type,
        "sanoid_installed": node.sanoid_installed,
        "sanoid_version": node.sanoid_version
    }
    
    if btrfs_info:
        result["btrfs"] = btrfs_info
    
    if pbs_info:
        result["pbs"] = pbs_info
    
    return result


@router.post("/{node_id}/install-sanoid")
async def install_sanoid_on_node(
    node_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Installa Sanoid su un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    success, output = await sanoid_service.install_sanoid(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        node.sanoid_installed = True
        log_audit(
            db, user.id, "sanoid_installed", "node",
            resource_id=node_id,
            details=f"Sanoid installed on: {node.name}",
            ip_address=request.client.host if request.client else None
        )
        db.commit()
    
    return {
        "success": success,
        "output": output
    }


@router.get("/{node_id}/datasets", response_model=List[DatasetResponse])
async def get_node_datasets(
    node_id: int,
    refresh: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene i dataset ZFS di un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    if refresh or not db.query(Dataset).filter(Dataset.node_id == node_id).first():
        # Refresh dalla macchina
        zfs_datasets = await ssh_service.get_zfs_datasets(
            hostname=node.hostname,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
        
        # Aggiorna database
        for zfs_ds in zfs_datasets:
            existing = db.query(Dataset).filter(
                Dataset.node_id == node_id,
                Dataset.name == zfs_ds["name"]
            ).first()
            
            if existing:
                existing.used = zfs_ds["used"]
                existing.available = zfs_ds["available"]
                existing.mountpoint = zfs_ds["mountpoint"]
                existing.last_updated = datetime.utcnow()
            else:
                new_ds = Dataset(
                    node_id=node_id,
                    name=zfs_ds["name"],
                    used=zfs_ds["used"],
                    available=zfs_ds["available"],
                    mountpoint=zfs_ds["mountpoint"]
                )
                db.add(new_ds)
        
        # Conta snapshot per ogni dataset
        snapshots = await ssh_service.get_snapshots(
            hostname=node.hostname,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
        
        snapshot_counts = {}
        for snap in snapshots:
            ds = snap["dataset"]
            snapshot_counts[ds] = snapshot_counts.get(ds, 0) + 1
        
        for ds in db.query(Dataset).filter(Dataset.node_id == node_id).all():
            ds.snapshot_count = snapshot_counts.get(ds.name, 0)
        
        db.commit()
    
    return db.query(Dataset).filter(Dataset.node_id == node_id).all()


@router.get("/{node_id}/vms")
async def get_node_vms(
    node_id: int,
    refresh: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene le VM di un nodo (dalla cache se disponibile, altrimenti live)"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    # Try cache first unless refresh is requested
    if not refresh:
        cached_vms = db.query(VirtualMachine).filter(VirtualMachine.node_id == node_id).all()
        if cached_vms:
            # Convert to dict compatible with proxmox_service format
            return [
                {
                    "vmid": vm.vmid,
                    "name": vm.name,
                    "type": vm.type,
                    "status": vm.status,
                    "maxmem": vm.memory,
                    "cpus": vm.cpus,
                    "uptime": vm.uptime
                } for vm in cached_vms
            ]
    
    # Live fetch
    guests = await proxmox_service.get_all_guests(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )

    # Optional: Update cache synchronously on miss?
    # For now, we rely on the Async Refresh button for population, 
    # but we could also update here.
    
    return guests


async def refresh_cache_task():
    """Background task wrapper for cache refresh"""
    db = SessionLocal()
    try:
        await cache_service.refresh_all_nodes(db)
    finally:
        db.close()


@router.post("/refresh-cache")
async def refresh_all_cache(
    background_tasks: BackgroundTasks,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Trigger update of all caches (VMs, etc)"""
    background_tasks.add_task(refresh_cache_task)
    return {"message": "Aggiornamento cache avviato in background"}


@router.get("/{node_id}/sanoid-status")
async def get_node_sanoid_status(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene lo stato di Sanoid su un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    return await sanoid_service.get_sanoid_status(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )


@router.post("/{node_id}/diagnostic")
async def run_node_diagnostic(
    node_id: int,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue lo script di diagnostica rapida sul nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    # Leggi lo script dal file locale
    script_path = Path(__file__).parent.parent / "scripts" / "quick_diagnostic.sh"
    try:
        if not script_path.exists():
            return {"success": False, "error": "Script di diagnostica non trovato sul server."}
        
        script_content = script_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Errore lettura script diagnostic: {e}")
        return {"success": False, "error": f"Errore interno: {e}"}
        
    # Esegui script
    result = await ssh_service.execute_script_from_content(
        hostname=node.hostname,
        script_content=script_content,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return {
        "success": result.success,
        "exit_code": result.exit_code,
        "output": result.stdout + "\n" + result.stderr
    }


@router.post("/{node_id}/set-auth-node")
async def set_as_auth_node(
    node_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Imposta questo nodo come nodo per autenticazione Proxmox"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    # Rimuovi flag da altri nodi
    db.query(Node).filter(Node.is_auth_node == True).update({"is_auth_node": False})
    
    # Imposta questo nodo
    node.is_auth_node = True
    
    log_audit(
        db, user.id, "auth_node_set", "node",
        resource_id=node_id,
        details=f"Set auth node: {node.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    
    return {"message": f"Nodo {node.name} impostato come nodo di autenticazione"}


@router.post("/{node_id}/run-sanoid")
async def run_sanoid_now(
    node_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue sanoid manualmente per triggerare uno snapshot immediato"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")
        
    from services.sanoid_config_service import sanoid_config_service
    
    success, message = await sanoid_config_service.run_sanoid(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(db, user.id, "run_sanoid", "node", resource_id=node_id, 
                  details="Manual sanoid snapshot triggered",
                  ip_address=request.client.host if request.client else None)
        return {"message": "Sanoid eseguito con successo", "output": message}
    else:
        raise HTTPException(status_code=500, detail=f"Errore esecuzione sanoid: {message}")
@router.get("/{node_id}/bridges")
async def get_node_bridges(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene la lista dei bridge di rete disponibili sul nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    bridges = await proxmox_service.get_node_bridges(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return {"bridges": bridges}


@router.get("/{node_id}/pbs-datastores")
async def get_pbs_datastores_for_node(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene la lista dei datastore di un nodo PBS"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
        
    if node.node_type != NodeType.PBS.value:
         raise HTTPException(status_code=400, detail="Il nodo non è un server PBS")
    
    datastores = await pbs_service.list_datastores(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return {"datastores": [ds.get("name") for ds in datastores]}


@router.get("/{node_id}/storages")
async def get_node_storages(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene la lista degli storage disponibili sul nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    from services.ssh_service import ssh_service
    
    # Ottieni lista storage
    result = await ssh_service.execute(
        hostname=node.hostname,
        command="pvesm status --output-format json 2>/dev/null || pvesm status",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        timeout=30
    )
    
    storages = []
    if result.success:
        try:
            import json
            storages_data = json.loads(result.stdout)
            for storage in storages_data:
                storages.append({
                    "storage": storage.get("storage", ""),
                    "type": storage.get("type", ""),
                    "status": storage.get("status", ""),
                    "avail": storage.get("avail", ""),
                    "used": storage.get("used", ""),
                    "total": storage.get("total", "")
                })
        except:
            # Fallback: parse text output
            for line in result.stdout.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    storages.append({
                        "storage": parts[0],
                        "type": parts[1],
                        "status": parts[2],
                        "avail": parts[3] if len(parts) > 3 else "N/A",
                        "used": parts[4] if len(parts) > 4 else "N/A",
                        "total": parts[5] if len(parts) > 5 else "N/A"
                    })
    
    return {"storages": storages}



