
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import json
import os
import logging

from services.load_balancer_service import load_balancer_service
from routers.auth import require_admin, User

router = APIRouter(prefix="/api/load-balancer", tags=["load-balancer"])
logger = logging.getLogger(__name__)

# Config persistence
CONFIG_FILE = os.environ.get("DAPX_CONFIG_DIR", "config") + "/load_balancer_config.json"

class LoadBalancerRunRequest(BaseModel):
    dry_run: bool = True
    config: Optional[Dict[str, Any]] = None

def load_saved_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    return {}

def save_config(config: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

@router.get("/analyze")
async def analyze_cluster(user: User = Depends(require_admin)):
    """Run cluster analysis and return calculated moves"""
    try:
        saved_config = load_saved_config()
        result = await load_balancer_service.analyze_cluster(config_override=saved_config)
        
        # Clean up result for frontend (remove non-serializable objects if any)
        # ProxLB data structure is mostly dicts/lists, should be fine.
        return result
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/execute")
async def execute_balancing(
    req: LoadBalancerRunRequest, 
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin)
):
    """Execute balancing (async)"""
    # For now synchronous because of library design, but run in thread pool via service
    try:
        saved_config = load_saved_config()
        if req.config:
            saved_config.update(req.config)
            
        result = await load_balancer_service.execute_balancing(config_override=saved_config, dry_run=req.dry_run)
        return result
    except Exception as e:
        logger.exception("Balancing failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config")
async def get_config(user: User = Depends(require_admin)):
    """Get current configuration"""
    # Return merged config with defaults
    saved = load_saved_config()
    default = load_balancer_service._get_default_config()
    # Simple merge for display
    # We want to show what is effectively used, or just what is saved?
    # Let's return saved, and also the effective full config
    effective = load_balancer_service._merge_config(saved)
    return {
        "saved": saved,
        "effective": effective
    }

@router.post("/config")
async def update_config(config: Dict[str, Any], user: User = Depends(require_admin)):
    """Update configuration"""
    save_config(config)
    return {"status": "success", "config": config}


# ============== Migration History API ==============

from database import get_db, LoadBalancerMigration
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class MigrationHistoryResponse(BaseModel):
    id: int
    guest_id: str
    guest_name: Optional[str] = None
    guest_type: str
    source_node: str
    target_node: str
    reason: Optional[str] = None
    status: str
    dry_run: bool
    source_cpu_percent: Optional[int] = None
    source_mem_percent: Optional[int] = None
    target_cpu_percent: Optional[int] = None
    target_mem_percent: Optional[int] = None
    error_message: Optional[str] = None
    proposed_at: datetime
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class MigrationHistoryCreate(BaseModel):
    guest_id: str
    guest_name: Optional[str] = None
    guest_type: str = "vm"
    source_node: str
    target_node: str
    reason: Optional[str] = None
    dry_run: bool = False
    source_cpu_percent: Optional[int] = None
    source_mem_percent: Optional[int] = None
    target_cpu_percent: Optional[int] = None
    target_mem_percent: Optional[int] = None

@router.get("/migrations", response_model=List[MigrationHistoryResponse])
async def list_migrations(
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Get migration history"""
    query = db.query(LoadBalancerMigration).order_by(LoadBalancerMigration.proposed_at.desc())
    
    if status:
        query = query.filter(LoadBalancerMigration.status == status)
    
    return query.limit(limit).all()

@router.get("/migrations/{migration_id}", response_model=MigrationHistoryResponse)
async def get_migration(
    migration_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Get single migration by ID"""
    migration = db.query(LoadBalancerMigration).filter(LoadBalancerMigration.id == migration_id).first()
    if not migration:
        raise HTTPException(status_code=404, detail="Migration not found")
    return migration

@router.post("/migrations", response_model=MigrationHistoryResponse)
async def record_migration(
    migration: MigrationHistoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Record a new migration (called after analysis or execution)"""
    db_migration = LoadBalancerMigration(
        guest_id=migration.guest_id,
        guest_name=migration.guest_name,
        guest_type=migration.guest_type,
        source_node=migration.source_node,
        target_node=migration.target_node,
        reason=migration.reason,
        dry_run=migration.dry_run,
        status="proposed" if migration.dry_run else "executing",
        source_cpu_percent=migration.source_cpu_percent,
        source_mem_percent=migration.source_mem_percent,
        target_cpu_percent=migration.target_cpu_percent,
        target_mem_percent=migration.target_mem_percent,
        triggered_by=user.id
    )
    db.add(db_migration)
    db.commit()
    db.refresh(db_migration)
    return db_migration

@router.patch("/migrations/{migration_id}/status")
async def update_migration_status(
    migration_id: int,
    status: str,
    error_message: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin)
):
    """Update migration status (completed, failed, skipped)"""
    migration = db.query(LoadBalancerMigration).filter(LoadBalancerMigration.id == migration_id).first()
    if not migration:
        raise HTTPException(status_code=404, detail="Migration not found")
    
    migration.status = status
    if status == "completed":
        migration.completed_at = datetime.utcnow()
    elif status == "executing":
        migration.executed_at = datetime.utcnow()
    if error_message:
        migration.error_message = error_message
    
    db.commit()
    return {"status": "updated", "migration_id": migration_id}
