
import os
import sys
import logging
import asyncio
from typing import Dict, Any, List, Optional
import json

from sqlalchemy.orm import Session
from database import SessionLocal, Node

# Add proxlb_lib to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
proxlb_path = os.path.join(current_dir, "proxlb_lib")
if proxlb_path not in sys.path:
    sys.path.append(proxlb_path)

# Now we can import from proxlb_lib
# Note: we wrap imports in try-except to avoid crashing if dependencies are missing during development
try:
    from utils.proxmox_api import ProxmoxApi
    from models.nodes import Nodes
    from models.features import Features
    from models.guests import Guests
    from models.groups import Groups
    from models.calculations import Calculations
    from models.balancing import Balancing
    from models.pools import Pools
    from models.ha_rules import HaRules
    from utils.helper import Helper
    PROXLB_AVAILABLE = True
except ImportError as e:
    logging.warning(f"ProxLB library import failed: {e}")
    PROXLB_AVAILABLE = False

logger = logging.getLogger(__name__)

class LoadBalancerService:
    def __init__(self):
        self.running = False
        self._last_analysis = None
        
    def _get_dynamic_config_from_db(self) -> Dict[str, Any]:
        """Fetch nodes and credentials from DB"""
        config_update = {
            "proxmox_api": {}
        }
        db = SessionLocal()
        try:
            nodes = db.query(Node).filter(Node.is_active == True).all()
            
            hosts = []
            token_id = None
            token_secret = None
            
            for node in nodes:
                # Add host
                if node.hostname and node.hostname not in hosts:
                    hosts.append(node.hostname)
                
                # Check for auth if we don't have it yet
                if not token_id and node.proxmox_api_token:
                    # Token format: user@pam!tokenid=secret or just user@pam!tokenid
                    # dapx typically stores: user@pam!tokenid=secret
                    if "=" in node.proxmox_api_token and "!" in node.proxmox_api_token:
                        try:
                            full_user, secret = node.proxmox_api_token.split("=", 1)
                            token_id = full_user
                            token_secret = secret
                        except ValueError:
                            pass
            
            # If nothing found in hosts, at least try standard IPs if known or container gateway
            if not hosts:
                hosts.append("192.168.40.4")
            elif "192.168.40.4" not in hosts:
                 hosts.append("192.168.40.4")

            config_update["proxmox_api"]["hosts"] = hosts
            
            if token_id and token_secret:
                config_update["proxmox_api"]["token_id"] = token_id
                config_update["proxmox_api"]["token_secret"] = token_secret
                
        except Exception as e:
            logger.error(f"Error fetching config from DB: {e}")
        finally:
            db.close()
            
        return config_update

    def _get_default_config(self) -> Dict[str, Any]:
        """Returns default configuration for ProxLB"""
        # In a real implementation, we would fetch credentials from DB or Vault
        # For now, we try to use environment variables or fallback
        # This assumes we are running on a node that can auth seamlessly or we have credentials
        
        # We need at least one host. We can try to use localhost if running on PVE
        hosts = ["localhost"]
        
        # Try to get credentials from environment
        user = os.getenv("PROXMOX_USER", "root@pam")
        password = os.getenv("PROXMOX_PASSWORD", "")
        token_id = os.getenv("PROXMOX_TOKEN_ID", "")
        token_secret = os.getenv("PROXMOX_TOKEN_SECRET", "")
        
        config = {
            "proxmox_api": {
                "hosts": hosts,
                "user": user,
                "ssl_verification": False,
                "timeout": 10
            },
            "proxmox_cluster": {
                "maintenance_nodes": [],
                "ignore_nodes": [],
                "overprovisioning": True
            },
            "balancing": {
                "enable": False, # Disabled by default for safety
                "enforce_affinity": False,
                "enforce_pinning": False,
                "parallel": False,
                "parallel_jobs": 1,
                "live": True,
                "with_local_disks": False,
                "with_conntrack_state": True,
                "balance_types": ["vm", "ct"],
                "max_job_validation": 1800,
                "memory_threshold": 75,
                "balanciness": 5,
                "method": "memory",
                "mode": "used", # 'assigned' | 'used' | 'psi'
                "balance_larger_guests_first": False,
                "node_resource_reserve": {
                    "defaults": {
                        "memory": 2
                    }
                }
            },
            "service": {
                "daemon": False,
                "log_level": "INFO"
            }
        }
        
        if password:
            config["proxmox_api"]["pass"] = password
        elif token_id and token_secret:
            config["proxmox_api"]["token_id"] = token_id
            config["proxmox_api"]["token_secret"] = token_secret
            
        return config

    def _merge_config(self, user_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merges default config with dynamic DB config and user provided config"""
        
        # 1. Base defaults
        config = self._get_default_config()
        
        # 2. Dynamic DB config
        db_config = self._get_dynamic_config_from_db()
        
        # Merge DB config into base
        if db_config.get("proxmox_api", {}).get("hosts"):
            config["proxmox_api"]["hosts"] = db_config["proxmox_api"]["hosts"]
        
        if db_config.get("proxmox_api", {}).get("token_id"):
             config["proxmox_api"]["token_id"] = db_config["proxmox_api"]["token_id"]
             config["proxmox_api"]["token_secret"] = db_config["proxmox_api"]["token_secret"]
        
        # 3. User overrides (highest priority)
        if user_config:
            # Deep merge simple implementation
            for k, v in user_config.items():
                if isinstance(v, dict) and k in config:
                    config[k].update(v)
                else:
                    config[k] = v
        
        # 4. Ensure hosts is always a list (fix for "hosts are not defined as a list type" error)
        hosts = config.get("proxmox_api", {}).get("hosts")
        if hosts is not None:
            if isinstance(hosts, str):
                # Convert comma-separated string to list
                config["proxmox_api"]["hosts"] = [h.strip() for h in hosts.split(",") if h.strip()]
            elif not isinstance(hosts, list):
                # If it's something else, try to convert
                config["proxmox_api"]["hosts"] = [str(hosts)]
        
        return config

    async def analyze_cluster(self, config_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Runs the analysis phase of ProxLB and returns the data structure.
        Does NOT perform any balancing actions.
        """
        if not PROXLB_AVAILABLE:
            raise Exception("ProxLB library not available")

        # Run in executor because ProxLB is synchronous
        return await asyncio.to_thread(self._run_analysis_sync, config_override)

    def _run_analysis_sync(self, config_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            proxlb_config = self._merge_config(config_override)
            
            # Force disable balancing execution for analysis only
            proxlb_config["balancing"]["enable"] = False
            
            # Initialize API
            # Note: ProxmoxApi init might fail if config is bad
            proxmox_api = ProxmoxApi(proxlb_config)
                
            # Helper.get_version("integrated") 
            
            # Core Logic extracted from main.py
            meta = {"meta": proxlb_config}
            
            # 1. Get Nodes
            nodes = Nodes.get_nodes(proxmox_api, proxlb_config)
            if not nodes:
                raise Exception("No nodes found or connection failed")
                
            meta = Features.validate_any_non_pve9_node(meta, nodes)
            
            # 2. Get Pools
            pools = Pools.get_pools(proxmox_api)
            
            # 3. Get HA Rules
            ha_rules = HaRules.get_ha_rules(proxmox_api, meta)
            
            # 4. Get Guests
            guests = Guests.get_guests(proxmox_api, pools, ha_rules, nodes, meta, proxlb_config)
            
            # 5. Get Groups
            groups = Groups.get_groups(guests, nodes)
            
            # Merge data
            proxlb_data = {**meta, **nodes, **guests, **pools, **ha_rules, **groups}
            
            # 6. Validate features
            Features.validate_available_features(proxlb_data)
            
            # 7. Calculations
            Calculations.set_node_assignments(proxlb_data)
            Calculations.set_node_hot(proxlb_data)
            Calculations.set_guest_hot(proxlb_data)
            
            # Arguments from CLI usually, here defaults
            best_node_arg = False 
            
            Calculations.get_most_free_node(proxlb_data, best_node_arg)
            Calculations.validate_affinity_map(proxlb_data)
            Calculations.relocate_guests_on_maintenance_nodes(proxlb_data)
            Calculations.get_balanciness(proxlb_data)
            
            # This calculates proposed moves
            Calculations.relocate_guests(proxlb_data)
            
            # Store for cache
            self._last_analysis = proxlb_data
            
            return proxlb_data

        except Exception as e:
            logger.exception("Error during analysis")
            raise Exception(f"Analysis failed: {e}")

    async def execute_balancing(self, config_override: Optional[Dict[str, Any]] = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        Executes the balancing based on fresh analysis.
        """
        if not PROXLB_AVAILABLE:
            raise Exception("ProxLB library not available")

        return await asyncio.to_thread(self._run_balancing_sync, config_override, dry_run)

    def _run_balancing_sync(self, config_override: Optional[Dict[str, Any]] = None, dry_run: bool = False) -> Dict[str, Any]:
        proxlb_config = self._merge_config(config_override)
        
        # Enable balancing in config if not dry run
        proxlb_config["balancing"]["enable"] = not dry_run
        
        # Initialize API
        proxmox_api = ProxmoxApi(proxlb_config)
        
        # Re-run analysis to get fresh state (logic duplicated from above for safety/freshness)
        # In optimized version we could pass the previous analysis if fresh enough
        meta = {"meta": proxlb_config}
        nodes = Nodes.get_nodes(proxmox_api, proxlb_config)
        meta = Features.validate_any_non_pve9_node(meta, nodes)
        pools = Pools.get_pools(proxmox_api)
        ha_rules = HaRules.get_ha_rules(proxmox_api, meta)
        guests = Guests.get_guests(proxmox_api, pools, ha_rules, nodes, meta, proxlb_config)
        groups = Groups.get_groups(guests, nodes)
        proxlb_data = {**meta, **nodes, **guests, **pools, **ha_rules, **groups}
        
        Features.validate_available_features(proxlb_data)
        Calculations.set_node_assignments(proxlb_data)
        Calculations.set_node_hot(proxlb_data)
        Calculations.set_guest_hot(proxlb_data)
        Calculations.get_most_free_node(proxlb_data, False)
        Calculations.validate_affinity_map(proxlb_data)
        Calculations.relocate_guests_on_maintenance_nodes(proxlb_data)
        Calculations.get_balanciness(proxlb_data)
        Calculations.relocate_guests(proxlb_data)
        
        result_log = []
        
        # Execute balancing
        if proxlb_config["balancing"].get("enable", False):
            if not dry_run:
                # Capture logs or output? 
                # Balancing class prints to log. We might not capture it easily unless we mock logger.
                # For now we rely on the fact it performs actions.
                # Use a custom logger adapter if needed.
                Balancing(proxmox_api, proxlb_data)
                result_log.append("Balancing executed.")
            else:
                result_log.append("Dry run: Balancing skipped.")
        else:
            result_log.append("Balancing disabled in config.")
            
        return {
            "data": proxlb_data,
            "log": result_log
        }

load_balancer_service = LoadBalancerService()
