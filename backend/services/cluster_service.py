"""
Cluster Service - Gestione nodi cluster Proxmox
Ported from ProxmoxScripts/Cluster/
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
import json
import re
import time
import asyncio

from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)

# Simple in-memory cache with TTL
class ClusterCache:
    """Cache in-memory con TTL per dati Cluster"""
    def __init__(self, default_ttl: int = 60):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._default_ttl = default_ttl
    
    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            value, expires = self._cache[key]
            if time.time() < expires:
                return value
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expires = time.time() + (ttl or self._default_ttl)
        self._cache[key] = (value, expires)
    
    def invalidate(self, key: str = None) -> None:
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

# Global cache instance
_cluster_cache = ClusterCache(default_ttl=60)


class ClusterService:
    """Servizio per gestione cluster Proxmox"""
    
    async def get_cluster_status(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa",
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Ottiene lo stato completo del cluster.
        """
        cache_key = f"cluster_status:{hostname}"
        
        if use_cache:
            cached = _cluster_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cluster status cache HIT for {hostname}")
                return cached
        
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
        
        _cluster_cache.set(cache_key, status)
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
        key_path: str = "/root/.ssh/id_rsa",
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Ottiene lista nodi del cluster con stato.
        """
        cache_key = f"cluster_nodes:{hostname}"
        
        if use_cache:
            cached = _cluster_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cluster nodes cache HIT for {hostname}")
                return cached
        
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
        
        _cluster_cache.set(cache_key, nodes)
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

    async def get_cluster_monitor_data(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, Any]:
        """
        Ottiene dati di monitoraggio leggeri per il cluster.
        Simile all'output di Proxmox LoadBalancer ma senza analisi complessa.
        """
        from services.proxmox_service import proxmox_service
        
        # 1. Get raw cluster resources
        resources = await proxmox_service.get_cluster_resources(
            hostname, port, username, key_path
        )
        
        nodes_data = {}
        guests_data = {}
        
        for res in resources:
            res_type = res.get("type")
            
            if res_type == "node":
                node_name = res.get("node")
                
                # Calculate percentages
                max_cpu = res.get("maxcpu", 1) or 1
                cpu_usage = res.get("cpu", 0) or 0
                # PVE API returns CPU as fractional (0.05 = 5%) for resources?
                # Actually for /cluster/resources, cpu is ratio 0.0-1.0
                cpu_percent = cpu_usage * 100
                
                max_mem = res.get("maxmem", 1) or 1
                mem_used = res.get("mem", 0) or 0
                mem_percent = (mem_used / max_mem) * 100 if max_mem > 0 else 0
                
                nodes_data[node_name] = {
                    "cpu_usage_percent": cpu_percent,
                    "memory_usage_percent": mem_percent,
                    "memory_used": mem_used,
                    "memory_total": max_mem,
                    "status": res.get("status", "unknown"),
                    # Pressure score dummy for frontend compatibility
                    "pressure_score": cpu_percent * 0.5 + mem_percent * 0.5,
                    "network_in": 0,  # Not available in simple resource list
                    "network_out": 0
                }
                
            elif res_type in ["qemu", "lxc"]:
                vmid = str(res.get("vmid"))
                guest_type = "vm" if res_type == "qemu" else "ct"
                
                 # Similar calculation for guests
                max_cpu = res.get("maxcpu", 1) or 1
                cpu_usage = res.get("cpu", 0) or 0
                cpu_percent = cpu_usage * 100
                
                max_mem = res.get("maxmem", 1) or 1
                mem_used = res.get("mem", 0) or 0
                
                guests_data[vmid] = {
                    "id": vmid,
                    "name": res.get("name", f"VM-{vmid}"),
                    "type": guest_type,
                    "node_current": res.get("node"),
                    "status": res.get("status"),
                    "cpu_used": cpu_percent,
                    "memory_used": mem_used,
                    "disk_used": res.get("disk", 0),
                    "networks": [] # Not available in simple scan
                }
                
        # 2. Fetch Network Metrics in parallel
        network_tasks = []
        node_names = list(nodes_data.keys())
        
        for node_name in node_names:
            network_tasks.append(
                self._get_node_network_metrics(hostname, node_name, port, username, key_path)
            )
        
        if network_tasks:
            results = await asyncio.gather(*network_tasks)
            for i, metrics in enumerate(results):
                node_name = node_names[i]
                if node_name in nodes_data:
                    nodes_data[node_name]["network_in"] = metrics["netin"]
                    nodes_data[node_name]["network_out"] = metrics["netout"]

        return {
            "nodes": nodes_data,
            "guests": guests_data
        }


    async def _get_node_network_metrics(
        self,
        hostname: str,
        target_node: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, float]:
        """Ottiene metriche di rete (netin/netout) per un nodo specifico"""
        # pvesh get /nodes/{node}/rrddata --timeframe hour --cf AVERAGE --output-format json
        cmd = f"pvesh get /nodes/{target_node}/rrddata --timeframe hour --cf AVERAGE --output-format json 2>/dev/null"
        
        result = await ssh_service.execute(hostname, cmd, port, username, key_path)
        
        metrics = {"netin": 0.0, "netout": 0.0}
        
        if result.success and result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                if data:
                    # Calculate average from list
                    # netin/netout keys exist directly in objects
                    netin_sum = sum(item.get("netin", 0) or 0 for item in data if item.get("netin") is not None)
                    netout_sum = sum(item.get("netout", 0) or 0 for item in data if item.get("netout") is not None)
                    count = len(data)
                    if count > 0:
                        metrics["netin"] = netin_sum / count
                        metrics["netout"] = netout_sum / count
            except Exception as e:
                logger.error(f"Error parsing RRD data for {target_node}: {e}")
                
        return metrics

    async def get_cluster_topology(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, Any]:
        """Recupera la topologia di rete del cluster (Corosync, Nodi, Guests)"""
        from services.proxmox_service import proxmox_service
        
        # 1. Base Resources
        resources = await proxmox_service.get_cluster_resources(hostname, port, username, key_path)
        
        nodes = sorted([r for r in resources if r.get('type') == 'node'], key=lambda x: x.get('node'))
        guests = [r for r in resources if r.get('type') in ['qemu', 'lxc']]
        
        # 2. Corosync Status (Single Call)
        corosync_task = self._get_corosync_info(hostname, port, username, key_path)
        
        # 3. Node Interfaces (Parallel)
        node_tasks = []
        node_names = []
        for node in nodes:
            node_name = node.get('node')
            node_names.append(node_name)
            node_tasks.append(self._get_node_interfaces(hostname, node_name, port, username, key_path))
            
        # 4. Guest Configs (Parallel)
        guest_tasks = []
        guest_ids = []
        for guest in guests:
            node = guest.get('node')
            vmid = str(guest.get('vmid'))
            gtype = 'qemu' if guest.get('type') == 'qemu' else 'lxc'
            
            # Skip guests on offline nodes if any
            if node:
                guest_ids.append(vmid)
                guest_tasks.append(self._get_guest_config(hostname, node, vmid, gtype, port, username, key_path))
            
        # Execute all details
        corosync_data = await corosync_task
        node_results = await asyncio.gather(*node_tasks)
        guest_results = await asyncio.gather(*guest_tasks)
        
        # Map Results
        nodes_map = {}
        for i, node_name in enumerate(node_names):
            nodes_map[node_name] = node_results[i]
            
        guests_map = {}
        for i, vmid in enumerate(guest_ids):
            guests_map[vmid] = guest_results[i]
            
        return {
            "corosync": corosync_data,
            "nodes": nodes_map,
            "guests": guests_map,
            "resource_list": resources # Raw list for reference
        }

    async def _get_corosync_info(self, hostname, port, username, key_path):
        """Parse /etc/pve/corosync.conf and checks status"""
        # Read conf
        cat_cmd = "cat /etc/pve/corosync.conf 2>/dev/null"
        res_cat = await ssh_service.execute(hostname, cat_cmd, port, username, key_path)
        
        rings = {}
        if res_cat.success:
            # Simple manual parsing or regex
            content = res_cat.stdout
            
            # Find node blocks
            # node {
            #   name: pve1
            #   ring0_addr: 1.2.3.4
            # }
            
            current_node = None
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('node {'):
                    current_node = {}
                elif line.startswith('}') and current_node is not None:
                     if 'name' in current_node:
                         rings[current_node['name']] = current_node
                     current_node = None
                elif current_node is not None:
                    if ':' in line:
                         k, v = line.split(':', 1)
                         current_node[k.strip()] = v.strip()
                         
        return {"rings": rings, "raw_conf": res_cat.stdout if res_cat.success else ""}

    async def _get_node_interfaces(self, hostname, target_node, port, username, key_path):
        """Get network interfaces for a node"""
        cmd = f"pvesh get /nodes/{target_node}/network --output-format json 2>/dev/null"
        res = await ssh_service.execute(hostname, cmd, port, username, key_path)
        if res.success and res.stdout.strip():
            try:
                return json.loads(res.stdout)
            except:
                pass
        return []

    async def _get_guest_config(self, hostname, target_node, vmid, gtype, port, username, key_path):
        """Get guest config (for network info)"""
        cmd = f"pvesh get /nodes/{target_node}/{gtype}/{vmid}/config --output-format json 2>/dev/null"
        res = await ssh_service.execute(hostname, cmd, port, username, key_path)
        
        metrics = {"networks": []}
        
        if res.success and res.stdout.strip():
            try:
                cfg = json.loads(res.stdout)
                # Parse network keys: net0, net1 OR network-interfaces (CT) often net0
                # For VM: net0: virtio=...,bridge=vmbr0...
                # For CT: net0: name=eth0,bridge=vmbr0...
                
                nets = []
                for k, v in cfg.items():
                    if k.startswith('net'):
                        # Parse string v
                        # Example: virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,firewall=1
                        net_info = {"id": k, "raw": v, "bridge": "", "mac": "", "tag": ""}
                        parts = v.split(',')
                        for p in parts:
                            if '=' in p:
                                pk, pv = p.split('=', 1)
                                pk = pk.strip()
                                pv = pv.strip()
                                if pk == 'bridge': net_info["bridge"] = pv
                                if pk == 'tag': net_info["tag"] = pv
                                if pk in ['virtio', 'e1000', 'vmxnet3', 'rtl8139']: net_info["mac"] = pv
                                if pk == 'hwaddr': net_info["mac"] = pv # CT
                        
                        # Fix for simple network definitions if any
                        if not net_info["bridge"] and 'bridge=' in v:
                             # Fallback regex search
                             import re
                             m = re.search(r'bridge=([^,\s]+)', v)
                             if m: net_info["bridge"] = m.group(1)
                             
                        nets.append(net_info)
                metrics["networks"] = nets
                metrics["name"] = cfg.get("name") # also capture name just in case
            except:
                pass
        return metrics

# Singleton instance
cluster_service = ClusterService()
