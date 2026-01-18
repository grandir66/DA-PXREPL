"""
Cluster Service - Gestione nodi cluster Proxmox
Ported from ProxmoxScripts/Cluster/
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
import json
import re

from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


class ClusterService:
    """Servizio per gestione cluster Proxmox"""
    
    async def get_cluster_status(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, Any]:
        """
        Ottiene lo stato completo del cluster.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="pvecm status 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path
        )
        
        status = {
            "cluster_name": "",
            "quorum": False,
            "version": "",
            "nodes": 0,
            "expected_votes": 0,
            "total_votes": 0,
            "quorum_votes": 0,
            "raw_output": result.stdout if result.success else result.stderr
        }
        
        if result.success:
            status.update(self._parse_pvecm_status(result.stdout))
        
        return status
    
    def _parse_pvecm_status(self, text: str) -> Dict[str, Any]:
        """Parse pvecm status output"""
        parsed = {}
        
        for line in text.split('\n'):
            line = line.strip()
            
            if line.startswith('Cluster information'):
                continue
            elif 'Cluster Name:' in line:
                parsed['cluster_name'] = line.split(':')[1].strip()
            elif 'Quorate:' in line:
                parsed['quorum'] = 'yes' in line.lower()
            elif 'Expected votes:' in line:
                try:
                    parsed['expected_votes'] = int(line.split(':')[1].strip())
                except ValueError:
                    pass
            elif 'Total votes:' in line:
                try:
                    parsed['total_votes'] = int(line.split(':')[1].strip())
                except ValueError:
                    pass
            elif 'Quorum:' in line and 'Quorate' not in line:
                try:
                    parsed['quorum_votes'] = int(line.split(':')[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
            elif 'Ring ID:' in line:
                parsed['ring_id'] = line.split(':')[1].strip() if ':' in line else ""
        
        return parsed
    
    async def get_cluster_nodes(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict[str, Any]]:
        """
        Ottiene lista nodi del cluster con stato.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="pvecm nodes 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path
        )
        
        nodes = []
        if result.success:
            nodes = self._parse_pvecm_nodes(result.stdout)
        
        return nodes
    
    def _parse_pvecm_nodes(self, text: str) -> List[Dict[str, Any]]:
        """Parse pvecm nodes output"""
        nodes = []
        
        for line in text.split('\n'):
            line = line.strip()
            # Skip header and empty lines
            if not line or 'Nodeid' in line or 'Votes' in line:
                continue
            
            parts = line.split()
            if len(parts) >= 3:
                # Format: Nodeid Votes Name [Status]
                node = {
                    "node_id": parts[0],
                    "votes": parts[1],
                    "name": parts[2],
                    "status": "online" if "(local)" in line or len(parts) == 3 else parts[3] if len(parts) > 3 else "unknown",
                    "is_local": "(local)" in line
                }
                nodes.append(node)
        
        return nodes
    
    async def get_node_ip(
        self,
        hostname: str,
        node_name: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Optional[str]:
        """
        Ottiene l'IP di un nodo dal cluster.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"pvesh get /cluster/status --output-format json 2>/dev/null | jq -r '.[] | select(.name==\"{node_name}\") | .ip'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and result.stdout.strip():
            return result.stdout.strip()
        return None
    
    async def check_node_has_guests(
        self,
        hostname: str,
        node_name: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, List[str]]:
        """
        Verifica se un nodo ha VM/CT.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"pvesh get /cluster/resources --type vm --output-format json 2>/dev/null | jq -r '.[] | select(.node==\"{node_name}\") | \"\\(.type) \\(.vmid)\"'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        guests = []
        if result.success and result.stdout.strip():
            guests = result.stdout.strip().split('\n')
        
        return len(guests) > 0, guests
    
    async def add_node_to_cluster(
        self,
        existing_cluster_host: str,
        new_node_ip: str,
        link0: Optional[str] = None,
        link1: Optional[str] = None,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Aggiunge un nodo al cluster.
        Port of ProxmoxScripts/Cluster/AddNodes.sh
        
        NOTA: Eseguito sul NUOVO nodo, non sul cluster esistente.
        """
        # Ottieni IP del cluster esistente
        cluster_ip = await self._get_host_ip(existing_cluster_host, port, username, key_path)
        if not cluster_ip:
            cluster_ip = existing_cluster_host
        
        # Costruisci comando
        cmd = f"pvecm add {cluster_ip}"
        if link0:
            cmd += f" --link0 {link0}"
        if link1:
            cmd += f" --link1 {link1}"
        
        # Esegui sul NUOVO nodo
        result = await ssh_service.execute(
            hostname=new_node_ip,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=120  # Join può richiedere tempo
        )
        
        if result.success:
            return True, f"Nodo {new_node_ip} aggiunto al cluster"
        else:
            return False, f"Errore: {result.stderr}"
    
    async def remove_node_from_cluster(
        self,
        hostname: str,
        node_name: str,
        force: bool = False,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Rimuove un nodo dal cluster.
        Port of ProxmoxScripts/Cluster/RemoveClusterNode.sh
        
        IMPORTANTE: Il nodo target deve essere SPENTO prima della rimozione.
        """
        # Verifica se il nodo ha VM (se non force)
        if not force:
            has_guests, guests = await self.check_node_has_guests(hostname, node_name, port, username, key_path)
            if has_guests:
                return False, f"Il nodo {node_name} ha ancora {len(guests)} VM/CT. Migrale o usa force=True"
        
        # Verifica se il nodo è online (dovrebbe essere offline)
        node_ip = await self.get_node_ip(hostname, node_name, port, username, key_path)
        if node_ip:
            ping_result = await ssh_service.execute(
                hostname=hostname,
                command=f"ping -c 1 -W 2 {node_ip} 2>/dev/null && echo 'ONLINE' || echo 'OFFLINE'",
                port=port,
                username=username,
                key_path=key_path
            )
            if "ONLINE" in ping_result.stdout:
                return False, f"Il nodo {node_name} ({node_ip}) è ancora online. Spegnilo prima della rimozione."
        
        # Rimuovi nodo
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"pvecm delnode {node_name}",
            port=port,
            username=username,
            key_path=key_path,
            timeout=60
        )
        
        if result.success:
            return True, f"Nodo {node_name} rimosso dal cluster"
        else:
            return False, f"Errore rimozione: {result.stderr}"
    
    async def clean_node_references(
        self,
        hostname: str,
        node_name: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Pulisce i riferimenti a un nodo rimosso su tutti i nodi del cluster.
        Port of cleanup logic from ProxmoxScripts/Cluster/RemoveClusterNode.sh
        """
        cleanup_cmd = f"""
ssh-keygen -R '{node_name}' >/dev/null 2>&1 || true
ssh-keygen -R '{node_name}.local' >/dev/null 2>&1 || true
sed -i '/{node_name}/d' /etc/ssh/ssh_known_hosts 2>/dev/null || true
rm -rf /etc/pve/nodes/{node_name} 2>/dev/null || true
echo "Cleanup completed for {node_name}"
"""
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=cleanup_cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            return True, f"Riferimenti a {node_name} puliti"
        else:
            return False, f"Errore cleanup: {result.stderr}"
    
    async def clean_node_on_all_nodes(
        self,
        hostname: str,
        node_name: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, bool]:
        """
        Esegue cleanup su tutti i nodi del cluster.
        """
        # Get all cluster nodes
        nodes = await self.get_cluster_nodes(hostname, port, username, key_path)
        results = {}
        
        for node in nodes:
            if node['name'] == node_name:
                continue  # Skip the node being removed
            
            # Get node IP
            node_ip = await self.get_node_ip(hostname, node['name'], port, username, key_path)
            if not node_ip:
                results[node['name']] = False
                continue
            
            success, _ = await self.clean_node_references(
                node_ip, node_name, port, username, key_path
            )
            results[node['name']] = success
        
        return results
    
    async def _get_host_ip(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Optional[str]:
        """Ottiene l'IP principale dell'host"""
        result = await ssh_service.execute(
            hostname=hostname,
            command="hostname -I | awk '{print $1}'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and result.stdout.strip():
            return result.stdout.strip()
        return None


# Singleton instance
cluster_service = ClusterService()
