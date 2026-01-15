"""
Router per gestione VM Proxmox
Con autenticazione
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import json # Missing import

from database import get_db, Node, VMRegistry, User, NodeType
from services.proxmox_service import proxmox_service
from services.ssh_service import ssh_service
from services.pbs_service import pbs_service
from services.sanoid_config_service import sanoid_config_service
from routers.auth import get_current_user, require_operator, log_audit

router = APIRouter()


# ============== Schemas ==============

class VMResponse(BaseModel):
    vmid: int
    name: str
    type: str  # qemu o lxc
    status: str


class VMDatasetResponse(BaseModel):
    vmid: int
    datasets: List[str]


class VMRegisterRequest(BaseModel):
    vmid: int
    vm_type: str = "qemu"
    config_content: Optional[str] = None

class SanoidConfig(BaseModel):
    enable: bool
    template: str
    autosnap: bool
    autoprune: bool
    hourly: int
    daily: int
    weekly: int
    monthly: int
    yearly: int

class ZFSRestoreRequest(BaseModel):
    snapshot_name: str
    action: str # "rollback" or "clone"
    new_vmid: Optional[int] = None # For clone action

class RestoreRequest(BaseModel):
    backup_id: str
    pbs_storage: str # Nome storage PBS sul nodo
    dest_storage: Optional[str] = None
    start_vm: bool = False
    target_node_id: Optional[int] = None # New for cross-node restore


# ============== Helper Functions ==============

def check_node_access(user: User, node: Node) -> bool:
    """Verifica se l'utente ha accesso al nodo"""
    if user.role == "admin":
        return True
    if user.allowed_nodes is None:
        return True
    return node.id in user.allowed_nodes


# ============== Endpoints ==============

@router.get("/node/{node_id}", response_model=List[VMResponse])
async def get_node_vms(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene tutte le VM e container di un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    guests = await proxmox_service.get_all_guests(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return [VMResponse(**g) for g in guests]


@router.get("/node/{node_id}/vm/{vmid}")
async def get_vm_details(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene i dettagli di una VM specifica"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    success, config = await proxmox_service.get_vm_config(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="VM non trovata")

    # Fetch snapshots
    snapshots = await proxmox_service.get_snapshots(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return {
        "vmid": vmid,
        "type": vm_type,
        "config": config,
        "snapshots": {"list": snapshots}
    }


@router.get("/node/{node_id}/vm/{vmid}/datasets", response_model=VMDatasetResponse)
async def get_vm_datasets(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Trova i dataset ZFS associati a una VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    datasets = await proxmox_service.find_vm_dataset(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return VMDatasetResponse(vmid=vmid, datasets=datasets)


@router.get("/node/{node_id}/vm/{vmid}/disks")
async def get_vm_disks(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene tutti i dischi di una VM con dimensioni e dataset ZFS.
    Usato per la creazione di job di replica VM-centrici.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    disks = await proxmox_service.get_vm_disks_with_size(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Calcola dimensione totale
    total_size = sum(d.get("size_bytes", 0) for d in disks)
    
    return {
        "vmid": vmid,
        "vm_type": vm_type,
        "disks": disks,
        "total_disks": len(disks),
        "total_size_bytes": total_size,
        "total_size": proxmox_service._format_size(total_size)
    }


@router.post("/node/{node_id}/register")
async def register_vm(
    node_id: int,
    vm_data: VMRegisterRequest,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Registra una VM su un nodo (dopo replica)"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    success, message, warnings = await proxmox_service.register_vm(
        hostname=node.hostname,
        vmid=vm_data.vmid,
        vm_type=vm_data.vm_type,
        config_content=vm_data.config_content,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "vm_registered", "vm",
            resource_id=vm_data.vmid,
            details=f"Registered VM {vm_data.vmid} on {node.name}",
            ip_address=request.client.host if request.client else None
        )
    
    return {"success": success, "message": message, "warnings": warnings}


@router.delete("/node/{node_id}/unregister/{vmid}")
async def unregister_vm(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Rimuove la registrazione di una VM (senza eliminare i dati)"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    success, message = await proxmox_service.unregister_vm(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "vm_unregistered", "vm",
            resource_id=vmid,
            details=f"Unregistered VM {vmid} on {node.name}",
            ip_address=request.client.host if request.client else None
        )
    
    return {"success": success, "message": message}


@router.get("/node/{node_id}/next-vmid")
async def get_next_vmid(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene il prossimo VMID disponibile"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    vmid = await proxmox_service.get_next_vmid(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return {"next_vmid": vmid}


# ============== VM Registry ==============

@router.get("/registry")
async def list_vm_registry(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista le VM registrate nel sistema"""
    vms = db.query(VMRegistry).all()
    return vms


@router.get("/registry/{vm_id}")
async def get_vm_registry(
    vm_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene info di una VM dal registro"""
    vm = db.query(VMRegistry).filter(VMRegistry.vm_id == vm_id).first()
    if not vm:
        raise HTTPException(status_code=404, detail="VM non trovata nel registro")
    return vm


# ============== Advanced VM Management ==============

class VMActionRequest(BaseModel):
    action: str # start, stop, shutdown, reboot

class SnapshotCreateRequest(BaseModel):
    snapname: str
    description: Optional[str] = ""
    vmstate: bool = False

@router.post("/node/{node_id}/vm/{vmid}/status/{action}")
async def manage_vm_lifecycle(
    node_id: int,
    vmid: int,
    action: str,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Gestisce stato VM (start, stop, etc)"""
    if action not in ["start", "stop", "shutdown", "reboot", "suspend", "resume"]:
        raise HTTPException(status_code=400, detail="Azione non valida")

    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    success, msg = await proxmox_service.vm_lifecycle_action(
        hostname=node.hostname,
        vmid=vmid,
        action=action,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not success:
        raise HTTPException(status_code=500, detail=msg)
    
    log_audit(db, user.id, f"vm_{action}", "vm", resource_id=vmid, details=f"{action} VM {vmid} on {node.name}")
    return {"message": msg}

@router.get("/node/{node_id}/vm/{vmid}/full-details")
async def get_vm_full_details_endpoint(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene dettagli completi VM (inclusi snapshot, IP, config)"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    details = await proxmox_service.get_vm_full_details(
        hostname=node.hostname,
        node_name=node.name, # Passiamo il nome nodo (non hostname) per pvesh
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    return details

@router.post("/node/{node_id}/vm/{vmid}/snapshot")
async def create_vm_snapshot(
    node_id: int,
    vmid: int,
    data: SnapshotCreateRequest,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea snapshot VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    success, msg = await proxmox_service.create_snapshot(
        hostname=node.hostname,
        vmid=vmid,
        snapname=data.snapname,
        description=data.description,
        vmstate=data.vmstate,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not success:
        raise HTTPException(status_code=500, detail=msg)
        
    log_audit(db, user.id, "vm_snapshot_create", "vm", resource_id=vmid, details=f"Created snapshot {data.snapname}")
    return {"message": msg}

@router.delete("/node/{node_id}/vm/{vmid}/snapshot/{snapname}")
async def delete_vm_snapshot(
    node_id: int,
    vmid: int,
    snapname: str,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina snapshot VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    success, msg = await proxmox_service.delete_snapshot(
        hostname=node.hostname,
        vmid=vmid,
        snapname=snapname,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not success:
        raise HTTPException(status_code=500, detail=msg)
        
    log_audit(db, user.id, "vm_snapshot_delete", "vm", resource_id=vmid, details=f"Deleted snapshot {snapname}")
    return {"message": msg}

@router.post("/node/{node_id}/vm/{vmid}/snapshot/{snapname}/rollback")
async def rollback_vm_snapshot(
    node_id: int,
    vmid: int,
    snapname: str,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Rollback snapshot VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    success, msg = await proxmox_service.rollback_snapshot(
        hostname=node.hostname,
        vmid=vmid,
        snapname=snapname,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not success:
        raise HTTPException(status_code=500, detail=msg)
    
    log_audit(db, user.id, "vm_snapshot_rollback", "vm", resource_id=vmid, details=f"Rollback to snapshot {snapname}")
    return {"message": msg}

    return list(all_vms.values())


    return list(all_vms.values())


@router.get("/node/{node_id}/vm/{vmid}/sanoid-config")
async def get_vm_sanoid_config(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene configurazione Sanoid per la VM (assume configurazione uniforme sui dischi)"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    # 1. Trova dataset
    datasets = await proxmox_service.find_vm_dataset(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not datasets:
        # Nessun dataset ZFS trovato
        return {
            "enable": False,
            "template": "production",
            "autosnap": True,
            "autoprune": True,
            "hourly": 0,
            "daily": 0,
            "weekly": 0,
            "monthly": 0,
            "yearly": 0,
            "datasets": []
        }

    # 2. Leggi config del primo dataset (assume coerenza VM-centrica)
    full_config = await sanoid_config_service.get_config(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Costruisci oggetto response base
    config = {
        "enable": False,
        "template": "production",
        "autosnap": True,
        "autoprune": True,
        "hourly": 0,
        "daily": 0,
        "weekly": 0,
        "monthly": 0,
        "yearly": 0,
        "datasets": datasets
    }
    
    primary_dataset = datasets[0]
    # Simple check se esiste sezione
    if f"[{primary_dataset}]" in full_config:
        config["enable"] = True
        try:
            import configparser
            cp = configparser.ConfigParser()
            cp.read_string(full_config)
            
            if cp.has_section(primary_dataset):
                sect = cp[primary_dataset]
                config["template"] = sect.get("use_template", "production")
                config["autosnap"] = sect.get("autosnap", "yes") == "yes"
                config["autoprune"] = sect.get("autoprune", "yes") == "yes"
                config["hourly"] = int(sect.get("hourly", 0))
                config["daily"] = int(sect.get("daily", 0))
                config["weekly"] = int(sect.get("weekly", 0))
                config["monthly"] = int(sect.get("monthly", 0))
                config["yearly"] = int(sect.get("yearly", 0))
        except Exception as e:
            print(f"Error parsing sanoid config: {e}")
            
    return config


@router.post("/node/{node_id}/vm/{vmid}/sanoid-config")
async def update_vm_sanoid_config(
    node_id: int,
    vmid: int,
    config: SanoidConfig,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna configurazione Sanoid per TUTTI i dataset della VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    datasets = await proxmox_service.find_vm_dataset(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not datasets:
        raise HTTPException(status_code=400, detail="Nessun dataset ZFS trovato per questa VM")

    results = []
    
    for ds in datasets:
        if config.enable:
            # TODO: sanoid_config_service.add_dataset_config deve supportare 'template'
            # Attualmente supporta parametri raw. 
            # Se uso template, hourly/daily etc vengono sovrascritti dal template se non specificati?
            # Da implementazione service: se passo hourly, lo scrive.
            # Se voglio usare template, dovrei potenzialmente omettere i valori o modificare il service.
            # Per ora passiamo i valori espliciti che sovrascrivono (policy 'production' + custom override)
            
            success, msg = await sanoid_config_service.add_dataset_config(
                hostname=node.hostname,
                dataset=ds,
                autosnap=config.autosnap,
                autoprune=config.autoprune,
                hourly=config.hourly,
                daily=config.daily,
                weekly=config.weekly,
                monthly=config.monthly,
                yearly=config.yearly,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
        else:
            success, msg = await sanoid_config_service.remove_dataset_config(
                hostname=node.hostname,
                dataset=ds,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
        results.append(f"{ds}: {msg}")
        
    log_audit(db, user.id, "vm_sanoid_config", "vm", resource_id=vmid, details=f"Update sanoid config enable={config.enable}")
    return {"message": "Configurazione aggiornata", "details": results}


@router.get("/node/{node_id}/vm/{vmid}/zfs-snapshots")
async def get_vm_zfs_snapshots(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene snapshot ZFS per tutti i dischi della VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    datasets = await proxmox_service.find_vm_dataset(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    all_snaps = []
    for ds in datasets:
        snaps = await sanoid_config_service.list_snapshots(
            hostname=node.hostname,
            dataset=ds,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
        for s in snaps:
            s["dataset"] = ds # Aggiungi ref al dataset
            all_snaps.append(s)
            
    return all_snaps


@router.post("/node/{node_id}/vm/{vmid}/zfs-restore")
async def restore_zfs_snapshot(
    node_id: int,
    vmid: int,
    data: ZFSRestoreRequest,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue rollback o clone di snapshot ZFS"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    datasets = await proxmox_service.find_vm_dataset(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )

    if data.action == "rollback":
        results = []
        for ds in datasets:
            cmd = f"zfs rollback -r {ds}@{data.snapshot_name}"
            res = await ssh_service.execute(node.hostname, cmd, node.ssh_port, node.ssh_user, node.ssh_key_path)
            if res.success:
                results.append(f"{ds}: OK")
            else:
                results.append(f"{ds}: Error {res.stderr}")
        
        log_audit(db, user.id, "vm_zfs_rollback", "vm", resource_id=vmid, details=f"Rollback to {data.snapshot_name}")
        return {"message": "Rollback eseguito", "details": results}
        
    elif data.action == "clone":
        if not data.new_vmid:
            raise HTTPException(status_code=400, detail="New VMID required for clone")
            
        success, msg = await proxmox_service.clone_vm_from_zfs_snapshot(
            hostname=node.hostname,
            source_vmid=vmid,
            new_vmid=data.new_vmid,
            snapshot_name=data.snapshot_name,
            datasets=datasets,
            vm_type=vm_type,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
        
        if success:
             log_audit(db, user.id, "vm_zfs_clone", "vm", resource_id=vmid, details=f"Cloned directly to VM {data.new_vmid}")
             return {"message": msg, "new_vmid": data.new_vmid}
        else:
             raise HTTPException(status_code=500, detail=msg)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")


class ZFSDeleteRequest(BaseModel):
    snapshot_name: str  # Can be a single name or 'all' to delete all


@router.delete("/node/{node_id}/vm/{vmid}/zfs-snapshots")
async def delete_zfs_snapshots(
    node_id: int,
    vmid: int,
    data: ZFSDeleteRequest,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina snapshot ZFS per una VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    datasets = await proxmox_service.find_vm_dataset(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )

    results = []
    for ds in datasets:
        if data.snapshot_name == 'all':
            # Delete all sanoid/manual snapshots for this dataset
            cmd = f"zfs list -t snapshot -H -o name {ds} 2>/dev/null | grep -E 'autosnap|syncoid|manual' | xargs -r -n1 zfs destroy"
        else:
            cmd = f"zfs destroy {ds}@{data.snapshot_name}"
        
        res = await ssh_service.execute(node.hostname, cmd, node.ssh_port, node.ssh_user, node.ssh_key_path)
        if res.success:
            results.append(f"{ds}: OK")
        else:
            results.append(f"{ds}: Error {res.stderr}")
    
    log_audit(db, user.id, "vm_zfs_delete_snapshot", "vm", resource_id=vmid, details=f"Deleted snapshot(s) {data.snapshot_name}")
    return {"message": "Snapshot eliminati", "details": results}


@router.post("/node/{node_id}/vm/{vmid}/snapshot-now")
async def create_zfs_snapshot_now(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea uno snapshot ZFS immediato (manuale) per la VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    datasets = await proxmox_service.find_vm_dataset(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    snapshot_name = f"manual_{timestamp}"
    
    results = []
    for ds in datasets:
        cmd = f"zfs snapshot {ds}@{snapshot_name}"
        res = await ssh_service.execute(node.hostname, cmd, node.ssh_port, node.ssh_user, node.ssh_key_path)
        if res.success:
            results.append(f"{ds}: OK")
        else:
            results.append(f"{ds}: Error {res.stderr}")

    log_audit(db, user.id, "vm_zfs_snapshot_now", "vm", resource_id=vmid, details=f"Created manual snapshot {snapshot_name}")
    return {"message": "Snapshot manuale creato", "snapshot_name": snapshot_name, "details": results}



    
@router.get("/node/{node_id}/vm/{vmid}/backups")
async def get_vm_backups(
    node_id: int,
    vmid: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene lista backup dal PBS configurato sul nodo.
    Cerca storage tipo 'pbs' sul nodo e interroga il PBS.
    Note: Se ci sono più storage PBS, li controlla tutti o richiede specifica?
    Per semplicità, cerchiamo tutti gli storage PBS attivi e aggreghiamo i backup per questo VMID.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato")

    # 1. Trova storage PBS sul nodo
    cmd = "pvesh get /storage --output-format json 2>/dev/null"
    result = await ssh_service.execute(node.hostname, cmd, node.ssh_port, node.ssh_user, node.ssh_key_path)
    
    all_backups = []
    
    if result.success and result.stdout.strip():
        try:
            storages = json.loads(result.stdout)
            pbs_storages = [
                s for s in storages 
                if s.get("type") == "pbs" and s.get("active") == 1
            ]
            
            from services.pbs_service import pbs_service
            
            # 2. Per ogni storage PBS, lista i backup
            for storage in pbs_storages:
                storage_id = storage.get("storage")
                # Lista backup via pvesh o proxmox-backup-client (usiamo pvesh per semplicità su storage configurato)
                # pvesh get /nodes/{node}/storage/{storage}/content --content backup --vmid {vmid}
                
                cmd_bak = f"pvesh get /nodes/{node.name}/storage/{storage_id}/content --content backup --vmid {vmid} --output-format json 2>/dev/null"
                res_bak = await ssh_service.execute(node.hostname, cmd_bak, node.ssh_port, node.ssh_user, node.ssh_key_path)
                
                if res_bak.success and res_bak.stdout.strip():
                    try:
                        backups = json.loads(res_bak.stdout)
                        for b in backups:
                            b["storage_id"] = storage_id # Aggiungi info storage
                            all_backups.append(b)
                    except json.JSONDecodeError:
                        pass
        except json.JSONDecodeError:
            pass
        except Exception:
             pass

    # 3. Fallback: Se non abbiamo trovato nulla, proviamo a interrogare direttamente i nodi PBS configurati nel DB
    if not all_backups:
        pbs_nodes = db.query(Node).filter(Node.node_type == NodeType.PBS.value, Node.is_active == True).all()
        for pbs_node in pbs_nodes:
            try:
                # Determina datastore (default 'backup' o configurato)
                datastore = pbs_node.pbs_datastore or "backup"
                
                # Utilizza pbs_service.list_backups per interrogare il PBS
                # Questo usa proxmox-backup-client gestendo auth e parsing json
                # Utilizza pbs_service.list_backups_api per interrogare il PBS via HTTP API
                # Questo evita problemi con SSH e certificati CLI
                snaps = await pbs_service.list_backups_api(
                    pbs_hostname=pbs_node.hostname,
                    datastore=datastore,
                    pbs_user=pbs_node.pbs_username or "root@pam",
                    pbs_password=pbs_node.pbs_password,
                    vm_id=vmid
                )
                
                for snap in snaps:
                     # Normalizzazione per frontend
                     # snapshot da list_backups ha già formato dict. Aggiungiamo metadati mancanti.
                     if "volid" not in snap:
                         snap["volid"] = f"{datastore}:{snap.get('backup-type')}/{snap.get('backup-id')}/{snap.get('backup-time')}"
                     
                     snap["vmid"] = vmid
                     snap["storage_id"] = datastore 
                     snap["pbs_node"] = pbs_node.name
                     all_backups.append(snap)
                             
            except Exception as e:
                print(f"Error querying PBS node {pbs_node.name}: {e}")

    return all_backups

@router.post("/node/{node_id}/vm/{vmid}/restore")
async def restore_vm_backup(
    node_id: int,
    vmid: int,
    data: RestoreRequest,
    vm_type: str = "qemu",
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Ripristina un backup. Sovrascrive la VM esistente (comportamento distruttivo!)"""
    # Determina nodo di esecuzione (Target Node)
    target_node_id = data.target_node_id if data.target_node_id else node_id
    
    node = db.query(Node).filter(Node.id == target_node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo target non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato al nodo target")

    # Verifica se l'ID VM è libero sul nodo target (se diverso da origine)
    # Se ripristiniamo su stesso nodo/vmid, è un overwrite.
    # Se ripristiniamo su altro nodo, dobbiamo garantire che l'ID sia libero o gestire conflitti?
    # Proxmox qmrestore fallisce se ID esiste? Sì, chiede --force.
    # Qui usiamo --force.
    
    # Costruisci comando qmrestore
    # qmrestore <storage>:<backup> <vmid> --storage <dest_storage> --force
    # data.backup_id deve essere completo (es: backup/vm/100/2023...)
    # ma qmrestore vuole storage:volume. 
    # data.backup_id che arriva dal frontend è di solito solo l'ID del backup (volid)?
    # Il frontend manda bak.volid che è "backup/vm/100/..."
    # qmrestore vuole "pbs-storage:backup/..."
    
    # Se il nodo target non ha lo storage PBS con lo stesso nome, fallirà.
    # Assumiamo configurazione coerente.
    
    cmd = f"qmrestore {data.pbs_storage}:{data.backup_id} {vmid} --force"
    if data.dest_storage:
        cmd += f" --storage {data.dest_storage}"
    if data.start_vm:
        cmd += " --start"
        
    cmd_bg = f"nohup {cmd} > /tmp/restore_{vmid}.log 2>&1 &"
    
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd_bg,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if result.success:
        actions_details = f"Started restore of {data.backup_id} on {node.name}"
        if target_node_id != node_id:
            actions_details += f" (Cross-node from {node_id})"
            
        log_audit(db, user.id, "vm_restore", "vm", resource_id=vmid, details=actions_details)
        return {"message": "Restore avviato in background. Controlla lo stato della VM sul nodo destinazione."}
    else:
        raise HTTPException(status_code=500, detail=f"Errore avvio restore: {result.stderr}")
