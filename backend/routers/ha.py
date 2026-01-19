"""
Router per gestione HA (High Availability) Proxmox
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from database import get_db, Node, User
from services.ha_service import ha_service
from services.cluster_service import cluster_service
from routers.auth import get_current_user, require_operator, log_audit

router = APIRouter()


# ============== Schemas ==============

class HAResourceRequest(BaseModel):
    vmid: int
    vm_type: str = "vm"  # vm or ct
    group: Optional[str] = None
    max_restart: int = 1
    max_relocate: int = 1
    state: str = "started"


class HAGroupRequest(BaseModel):
    name: str
    nodes: List[str]  # ["node1:100", "node2:50"] or ["node1", "node2"]
    restricted: bool = False
    nofailback: bool = False


class HAStateRequest(BaseModel):
    state: str  # started, stopped, disabled, ignored


# ============== HA Resources ==============

@router.get("/node/{node_id}/resources")
async def get_ha_resources(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutte le risorse HA configurate"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    resources = await ha_service.get_ha_resources(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return resources


@router.get("/node/{node_id}/status")
async def get_ha_status(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene lo stato HA completo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    status = await ha_service.get_ha_status(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return status


@router.post("/node/{node_id}/resources")
async def add_ha_resource(
    node_id: int,
    data: HAResourceRequest,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiunge una risorsa (VM/CT) all'HA"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    success, message = await ha_service.add_resource_to_ha(
        hostname=node.hostname,
        vmid=data.vmid,
        vm_type=data.vm_type,
        group=data.group,
        max_restart=data.max_restart,
        max_relocate=data.max_relocate,
        state=data.state,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "ha_resource_add", "ha",
            resource_id=data.vmid,
            details=f"Added {data.vm_type}:{data.vmid} to HA",
            ip_address=request.client.host if request.client else None
        )
    
    return {"success": success, "message": message}


@router.delete("/node/{node_id}/resources/{vmid}")
async def remove_ha_resource(
    node_id: int,
    vmid: int,
    vm_type: str = "vm",
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Rimuove una risorsa dall'HA"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    success, message = await ha_service.remove_resource_from_ha(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "ha_resource_remove", "ha",
            resource_id=vmid,
            details=f"Removed {vm_type}:{vmid} from HA",
            ip_address=request.client.host if request and request.client else None
        )
    
    return {"success": success, "message": message}


@router.post("/node/{node_id}/resources/{vmid}/state")
async def set_ha_resource_state(
    node_id: int,
    vmid: int,
    data: HAStateRequest,
    vm_type: str = "vm",
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Imposta lo stato di una risorsa HA"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    success, message = await ha_service.set_resource_state(
        hostname=node.hostname,
        vmid=vmid,
        vm_type=vm_type,
        state=data.state,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return {"success": success, "message": message}


# ============== HA Groups ==============

@router.get("/node/{node_id}/groups")
async def get_ha_groups(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i gruppi HA"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    groups = await ha_service.get_ha_groups(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return groups


@router.get("/node/{node_id}/groups/{group_name}")
async def get_ha_group_detail(
    node_id: int,
    group_name: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene dettagli di un gruppo HA"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    group = await ha_service.get_ha_group_detail(
        hostname=node.hostname,
        group_name=group_name,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return group


@router.post("/node/{node_id}/groups")
async def create_ha_group(
    node_id: int,
    data: HAGroupRequest,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo gruppo HA"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    success, message = await ha_service.create_ha_group(
        hostname=node.hostname,
        group_name=data.name,
        nodes=data.nodes,
        restricted=data.restricted,
        nofailback=data.nofailback,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "ha_group_create", "ha",
            details=f"Created HA group '{data.name}' with nodes: {data.nodes}",
            ip_address=request.client.host if request.client else None
        )
    
    return {"success": success, "message": message}


@router.delete("/node/{node_id}/groups/{group_name}")
async def delete_ha_group(
    node_id: int,
    group_name: str,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina un gruppo HA"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    success, message = await ha_service.delete_ha_group(
        hostname=node.hostname,
        group_name=group_name,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "ha_group_delete", "ha",
            details=f"Deleted HA group '{group_name}'",
            ip_address=request.client.host if request and request.client else None
        )
    
    return {"success": success, "message": message}


# ============== Cluster Management ==============

@router.get("/node/{node_id}/cluster/status")
async def get_cluster_status(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene lo stato del cluster Proxmox"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    status = await cluster_service.get_cluster_status(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return status


@router.get("/node/{node_id}/cluster/nodes")
async def get_cluster_nodes(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista i nodi del cluster con stato"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    nodes = await cluster_service.get_cluster_nodes(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return nodes


class AddNodeRequest(BaseModel):
    new_node_ip: str
    link0: Optional[str] = None
    link1: Optional[str] = None


@router.post("/node/{node_id}/cluster/nodes")
async def add_node_to_cluster(
    node_id: int,
    data: AddNodeRequest,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Aggiunge un nuovo nodo al cluster.
    ATTENZIONE: Operazione rischiosa, richiede conferma.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    success, message = await cluster_service.add_node_to_cluster(
        existing_cluster_host=node.hostname,
        new_node_ip=data.new_node_ip,
        link0=data.link0,
        link1=data.link1,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "cluster_node_add", "cluster",
            details=f"Added node {data.new_node_ip} to cluster",
            ip_address=request.client.host if request.client else None
        )
    
    return {"success": success, "message": message}


class RemoveNodeRequest(BaseModel):
    force: bool = False


@router.delete("/node/{node_id}/cluster/nodes/{node_name}")
async def remove_node_from_cluster(
    node_id: int,
    node_name: str,
    force: bool = False,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Rimuove un nodo dal cluster.
    ATTENZIONE: Il nodo deve essere SPENTO prima della rimozione.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    success, message = await cluster_service.remove_node_from_cluster(
        hostname=node.hostname,
        node_name=node_name,
        force=force,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "cluster_node_remove", "cluster",
            details=f"Removed node {node_name} from cluster",
            ip_address=request.client.host if request and request.client else None
        )
    
    return {"success": success, "message": message}


@router.post("/node/{node_id}/cluster/nodes/{node_name}/clean")
async def clean_node_references(
    node_id: int,
    node_name: str,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Pulisce i riferimenti a un nodo rimosso su tutti i nodi del cluster.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    results = await cluster_service.clean_node_on_all_nodes(
        hostname=node.hostname,
        node_name=node_name,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    log_audit(
        db, user.id, "cluster_node_clean", "cluster",
        details=f"Cleaned references to node {node_name}",
        ip_address=request.client.host if request and request.client else None
    )
    
    return {"results": results, "node_name": node_name}


# ============== Enhanced HA Data ==============

@router.get("/node/{node_id}/available-guests")
async def get_available_guests(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene tutte le VM/CT del cluster disponibili per l'aggiunta all'HA.
    Mostra nome, VMID, nodo, stato e se già in HA.
    """
    from services.proxmox_service import proxmox_service
    
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    # Ottieni risorse cluster
    resources = await proxmox_service.get_cluster_resources(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Ottieni risorse già in HA
    ha_resources = await ha_service.get_ha_resources(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        use_cache=True
    )
    
    # Set di risorse già in HA
    ha_sids = set()
    for res in ha_resources:
        sid = res.get("sid", "")
        if sid:
            ha_sids.add(sid)
    
    # Filtra solo VM e CT
    guests = []
    for res in resources:
        res_type = res.get("type", "")
        if res_type in ["qemu", "lxc"]:
            vmid = res.get("vmid")
            sid = f"{'vm' if res_type == 'qemu' else 'ct'}:{vmid}"
            
            guests.append({
                "vmid": vmid,
                "name": res.get("name", f"VM-{vmid}"),
                "type": "vm" if res_type == "qemu" else "ct",
                "node": res.get("node", ""),
                "status": res.get("status", "unknown"),
                "cpu": res.get("cpu", 0),
                "maxcpu": res.get("maxcpu", 0),
                "mem": res.get("mem", 0),
                "maxmem": res.get("maxmem", 0),
                "uptime": res.get("uptime", 0),
                "in_ha": sid in ha_sids,
                "sid": sid
            })
    
    # Ordina per VMID
    guests.sort(key=lambda x: x["vmid"])
    
    return guests


@router.get("/node/{node_id}/complete-data")
async def get_ha_complete_data(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Endpoint completo che ritorna tutti i dati necessari per la pagina HA:
    - guests: tutte le VM/CT con stato HA
    - ha_resources: risorse attualmente in HA
    - ha_groups: gruppi HA configurati
    - cluster_nodes: nodi del cluster
    - cluster_status: stato quorum
    """
    from services.proxmox_service import proxmox_service
    
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    # Esegui tutte le chiamate in parallelo
    import asyncio
    
    resources_task = proxmox_service.get_cluster_resources(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    ha_resources_task = ha_service.get_ha_resources(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        use_cache=True
    )
    
    ha_groups_task = ha_service.get_ha_groups(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        use_cache=True
    )
    
    cluster_nodes_task = cluster_service.get_cluster_nodes(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        use_cache=True
    )
    
    cluster_status_task = cluster_service.get_cluster_status(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        use_cache=True
    )
    
    # Attendi tutte le chiamate
    resources, ha_resources, ha_groups, cluster_nodes, cluster_status = await asyncio.gather(
        resources_task, ha_resources_task, ha_groups_task, cluster_nodes_task, cluster_status_task
    )
    
    # Mappa HA resources per lookup veloce
    ha_map = {}
    for res in ha_resources:
        sid = res.get("sid", "")
        if sid:
            ha_map[sid] = res
    
    # Processa guests
    guests = []
    for res in resources:
        res_type = res.get("type", "")
        if res_type in ["qemu", "lxc"]:
            vmid = res.get("vmid")
            sid = f"{'vm' if res_type == 'qemu' else 'ct'}:{vmid}"
            ha_info = ha_map.get(sid, {})
            
            guests.append({
                "vmid": vmid,
                "name": res.get("name", f"VM-{vmid}"),
                "type": "vm" if res_type == "qemu" else "ct",
                "node": res.get("node", ""),
                "status": res.get("status", "unknown"),
                "in_ha": sid in ha_map,
                "ha_state": ha_info.get("state", ""),
                "ha_group": ha_info.get("group", ""),
                "sid": sid
            })
    
    guests.sort(key=lambda x: x["vmid"])
    
    return {
        "guests": guests,
        "ha_resources": ha_resources,
        "ha_groups": ha_groups,
        "cluster_nodes": cluster_nodes,
        "cluster_status": cluster_status,
        "node_id": node_id
    }

