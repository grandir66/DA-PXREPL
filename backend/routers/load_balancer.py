
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
