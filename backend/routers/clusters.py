"""
Clusters Router - API per gestione cluster Proxmox multipli
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import logging

from database import get_db, ProxmoxCluster

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


# ============== SCHEMAS ==============

class ClusterCreate(BaseModel):
    name: str
    hosts: str
    api_user: Optional[str] = None
    api_token_id: Optional[str] = None
    api_token_secret: Optional[str] = None
    api_password: Optional[str] = None
    verify_ssl: bool = False
    is_default: bool = False


class ClusterUpdate(BaseModel):
    name: Optional[str] = None
    hosts: Optional[str] = None
    api_user: Optional[str] = None
    api_token_id: Optional[str] = None
    api_token_secret: Optional[str] = None
    api_password: Optional[str] = None
    verify_ssl: Optional[bool] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class ClusterResponse(BaseModel):
    id: int
    name: str
    hosts: str
    api_user: Optional[str]
    verify_ssl: bool
    is_initialized: bool
    cluster_name: Optional[str]
    node_count: int
    quorum_ok: bool
    last_check: Optional[datetime]
    last_error: Optional[str]
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============== ENDPOINTS ==============

@router.get("", response_model=List[ClusterResponse])
async def list_clusters(db: Session = Depends(get_db)):
    """Lista tutti i cluster configurati"""
    clusters = db.query(ProxmoxCluster).filter(ProxmoxCluster.is_active == True).all()
    return clusters


@router.get("/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(cluster_id: int, db: Session = Depends(get_db)):
    """Ottieni dettagli di un cluster"""
    cluster = db.query(ProxmoxCluster).filter(ProxmoxCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.post("", response_model=ClusterResponse)
async def create_cluster(data: ClusterCreate, db: Session = Depends(get_db)):
    """Crea un nuovo cluster"""
    # Check if name already exists
    existing = db.query(ProxmoxCluster).filter(ProxmoxCluster.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Cluster with this name already exists")
    
    # If is_default, unset other defaults
    if data.is_default:
        db.query(ProxmoxCluster).filter(ProxmoxCluster.is_default == True).update({"is_default": False})
    
    cluster = ProxmoxCluster(
        name=data.name,
        hosts=data.hosts,
        api_user=data.api_user,
        api_token_id=data.api_token_id,
        api_token_secret=data.api_token_secret,
        api_password=data.api_password,
        verify_ssl=data.verify_ssl,
        is_default=data.is_default
    )
    
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    
    logger.info(f"Created cluster: {cluster.name}")
    return cluster


@router.put("/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(cluster_id: int, data: ClusterUpdate, db: Session = Depends(get_db)):
    """Aggiorna un cluster esistente"""
    cluster = db.query(ProxmoxCluster).filter(ProxmoxCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    update_data = data.dict(exclude_unset=True)
    
    # If setting as default, unset others
    if update_data.get("is_default"):
        db.query(ProxmoxCluster).filter(
            ProxmoxCluster.id != cluster_id,
            ProxmoxCluster.is_default == True
        ).update({"is_default": False})
    
    for key, value in update_data.items():
        setattr(cluster, key, value)
    
    cluster.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cluster)
    
    logger.info(f"Updated cluster: {cluster.name}")
    return cluster


@router.delete("/{cluster_id}")
async def delete_cluster(cluster_id: int, db: Session = Depends(get_db)):
    """Elimina un cluster (soft delete)"""
    cluster = db.query(ProxmoxCluster).filter(ProxmoxCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Soft delete
    cluster.is_active = False
    cluster.updated_at = datetime.utcnow()
    db.commit()
    
    logger.info(f"Deleted cluster: {cluster.name}")
    return {"message": f"Cluster '{cluster.name}' deleted successfully"}


@router.post("/{cluster_id}/test")
async def test_cluster_connection(cluster_id: int, db: Session = Depends(get_db)):
    """Testa la connessione al cluster"""
    cluster = db.query(ProxmoxCluster).filter(ProxmoxCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    try:
        # Import here to avoid circular imports
        from services.proxmox_service import proxmox_service
        
        # Parse first host
        hosts = [h.strip() for h in cluster.hosts.split(",") if h.strip()]
        if not hosts:
            raise HTTPException(status_code=400, detail="No hosts configured")
        
        first_host = hosts[0]
        
        # Try to get cluster status
        # This is a simplified test - could be enhanced
        status = await proxmox_service.get_cluster_status(
            hostname=first_host,
            port=22,  # Default
            username="root",
            key_path="/root/.ssh/id_rsa"
        )
        
        # Update cluster with status
        cluster.is_initialized = True
        cluster.cluster_name = status.get("cluster_name", "Unknown")
        cluster.quorum_ok = status.get("quorum", False)
        cluster.node_count = len(status.get("nodes", []))
        cluster.last_check = datetime.utcnow()
        cluster.last_error = None
        db.commit()
        
        return {
            "success": True,
            "cluster_name": cluster.cluster_name,
            "quorum": cluster.quorum_ok,
            "nodes": cluster.node_count
        }
        
    except Exception as e:
        cluster.last_error = str(e)
        cluster.last_check = datetime.utcnow()
        db.commit()
        
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")


@router.get("/default/current", response_model=ClusterResponse)
async def get_default_cluster(db: Session = Depends(get_db)):
    """Ottieni il cluster di default"""
    cluster = db.query(ProxmoxCluster).filter(
        ProxmoxCluster.is_default == True,
        ProxmoxCluster.is_active == True
    ).first()
    
    if not cluster:
        # Fallback to first active cluster
        cluster = db.query(ProxmoxCluster).filter(
            ProxmoxCluster.is_active == True
        ).first()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="No cluster configured")
    
    return cluster
