"""
High Availability Service - Gestione HA Proxmox
Ported from ProxmoxScripts/HighAvailability/
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
import json
import re

from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


class HAService:
    """Servizio per gestione High Availability Proxmox"""
    
    async def get_ha_status(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, Any]:
        """
        Ottiene lo stato generale dell'HA cluster.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="ha-manager status --output-format json 2>/dev/null || ha-manager status",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            try:
                # Try JSON first
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                # Parse text output
                return self._parse_ha_status_text(result.stdout)
        
        return {"error": result.stderr, "resources": [], "groups": []}
    
    def _parse_ha_status_text(self, text: str) -> Dict[str, Any]:
        """Parse ha-manager status text output"""
        resources = []
        for line in text.strip().split('\n'):
            if line.strip() and not line.startswith('quorum'):
                # Format: vm:100 started node1
                parts = line.split()
                if len(parts) >= 2:
                    sid = parts[0]
                    state = parts[1] if len(parts) > 1 else "unknown"
                    node = parts[2] if len(parts) > 2 else ""
                    
                    # Parse sid (vm:100 or ct:200)
                    if ':' in sid:
                        res_type, vmid = sid.split(':', 1)
                    else:
                        res_type, vmid = "vm", sid
                    
                    resources.append({
                        "sid": sid,
                        "type": res_type,
                        "vmid": vmid,
                        "state": state,
                        "node": node
                    })
        
        return {"resources": resources}
    
    async def get_ha_resources(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict[str, Any]]:
        """
        Lista risorse HA configurate.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="pvesh get /cluster/ha/resources --output-format json 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path
        )
        
        resources = []
        if result.success and result.stdout.strip():
            try:
                resources = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse HA resources JSON from {hostname}")
        
        return resources
    
    async def get_ha_groups(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict[str, Any]]:
        """
        Lista gruppi HA configurati.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="pvesh get /cluster/ha/groups --output-format json 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path
        )
        
        groups = []
        if result.success and result.stdout.strip():
            try:
                groups = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse HA groups JSON from {hostname}")
        
        return groups
    
    async def add_resource_to_ha(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "vm",
        group: Optional[str] = None,
        max_restart: int = 1,
        max_relocate: int = 1,
        state: str = "started",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Aggiunge una risorsa all'HA.
        Port of ProxmoxScripts/HighAvailability/AddResources.sh
        """
        sid = f"{vm_type}:{vmid}"
        
        cmd = f"ha-manager add {sid} --state {state} --max_restart {max_restart} --max_relocate {max_relocate}"
        if group:
            cmd += f" --group {group}"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            return True, f"Risorsa {sid} aggiunta all'HA"
        else:
            return False, f"Errore: {result.stderr}"
    
    async def remove_resource_from_ha(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "vm",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Rimuove una risorsa dall'HA.
        """
        sid = f"{vm_type}:{vmid}"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"ha-manager remove {sid}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            return True, f"Risorsa {sid} rimossa dall'HA"
        else:
            return False, f"Errore: {result.stderr}"
    
    async def set_resource_state(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "vm",
        state: str = "started",  # started, stopped, disabled, ignored
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Imposta lo stato di una risorsa HA.
        """
        sid = f"{vm_type}:{vmid}"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"ha-manager set {sid} --state {state}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            return True, f"Stato di {sid} impostato a {state}"
        else:
            return False, f"Errore: {result.stderr}"
    
    async def create_ha_group(
        self,
        hostname: str,
        group_name: str,
        nodes: List[str],
        restricted: bool = False,
        nofailback: bool = False,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Crea un nuovo gruppo HA.
        Port of ProxmoxScripts/HighAvailability/CreateHAGroup.sh
        """
        # Nodes format: node1:priority,node2:priority or just node1,node2
        nodes_str = ",".join(nodes)
        
        cmd = f"ha-manager groupadd {group_name} --nodes {nodes_str}"
        if restricted:
            cmd += " --restricted 1"
        if nofailback:
            cmd += " --nofailback 1"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            return True, f"Gruppo HA '{group_name}' creato"
        else:
            return False, f"Errore: {result.stderr}"
    
    async def delete_ha_group(
        self,
        hostname: str,
        group_name: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Elimina un gruppo HA.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"ha-manager groupremove {group_name}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            return True, f"Gruppo HA '{group_name}' eliminato"
        else:
            return False, f"Errore: {result.stderr}"
    
    async def get_ha_group_detail(
        self,
        hostname: str,
        group_name: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, Any]:
        """
        Ottiene dettagli di un gruppo HA specifico.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"pvesh get /cluster/ha/groups/{group_name} --output-format json 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
        
        return {"error": "Group not found or parse error"}


# Singleton instance
ha_service = HAService()
