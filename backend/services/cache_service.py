from sqlalchemy.orm import Session
from datetime import datetime
import logging
import asyncio

from database import Node, VirtualMachine, NodeType
from services.proxmox_service import proxmox_service
from services.pbs_service import pbs_service

logger = logging.getLogger(__name__)

class CacheService:
    async def refresh_all_nodes(self, db: Session):
        """Aggiorna la cache per tutti i nodi attivi"""
        nodes = db.query(Node).filter(Node.is_active == True).all()
        logger.info(f"Starting cache refresh for {len(nodes)} nodes")
        
        results = {}
        for node in nodes:
            try:
                # Esegui ogni nodo in un task separato o sequenziale?
                # Sequenziale è più sicuro per il DB session sqlite (se usato)
                await self.refresh_node_vms(db, node)
                
                # Se è un nodo PBS, aggiorna datastore?
                # TODO: Implement PBS caching if needed
                
                results[node.name] = "OK"
            except Exception as e:
                logger.error(f"Error refreshing node {node.name}: {e}")
                results[node.name] = str(e)
        
        logger.info("Cache refresh completed")
        return results

    async def refresh_node_vms(self, db: Session, node: Node):
        """Aggiorna cache VM e dettagli Host per un singolo nodo"""
        if not node.is_online and not node.is_auth_node:
             # Se non è online, si potrebbe skippare, ma proviamo comunque
             pass

        try:
            # 1. Aggiorna Host Info (Advanced Data)
            # Utilizza host_info_service per raccogliere metriche avanzate (CPU, RAM specifica, Storage, Network)
            from services.host_info_service import HostInfoService
            host_service = HostInfoService()
            # Nota: update_host_details crea la sua sessione, quindi è autonomo
            await host_service.update_host_details(node.id)

            logger.debug(f"Fetching Cluster Resources for node {node.name}")
            
            # 2. Ottieni lista VM/CT con metriche avanzate (via pvesh cluster resource)
            # Questo ritorna CPU usage, MaxMem, Uptime, etc.
            resources = await proxmox_service.get_cluster_resources(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            # Filtra risorse per questo nodo
            # La risorsa ha campo 'node' che deve combaciare con node.name
            node_resources = [
                r for r in resources 
                if r.get('node') == node.name and r.get('type') in ['qemu', 'lxc']
            ]
            
            # Se la lista è vuota ma get_cluster_resources ha avuto successo, potrebbe essere 
            # che il nodo non è parte di un cluster (standalone) o il nome nodo non combacia.
            # In caso di standalone, pvesh get /cluster/resources ritorna comunque le risorse locali?
            # Sì, su standalone ritorna le risorse del nodo locale.
            # Se node.name nel DB è diverso da quello Proxmox, potremmo avere problemi.
            # Fallback: se node_resources vuoto, prova get_all_guests (metodo classico via qm list)
            
            guests = []
            if node_resources:
                for r in node_resources:
                    guests.append({
                        "vmid": int(r.get('vmid')),
                        "name": r.get('name'),
                        "type": r.get('type'), # qemu o lxc
                        "status": r.get('status'),
                        "maxmem": int(r.get('maxmem', 0)), # Bytes
                        "cpus": int(r.get('maxcpu', 0)),
                        "uptime": int(r.get('uptime', 0))
                    })
            else:
                # Fallback legacy
                logger.warning(f"No cluster resources found for node {node.name}, falling back to qm/pct list")
                guests_legacy = await proxmox_service.get_all_guests(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path
                )
                # Adatta formato
                for g in guests_legacy:
                    guests.append({
                        "vmid": int(g.get('vmid')),
                        "name": g.get('name'),
                        "type": g.get('type'),
                        "status": g.get('status'),
                        "maxmem": 0, # Legacy fetch non ha questi dati
                        "cpus": 0,
                        "uptime": 0
                    })

            # Sync DB
            current_vms = {vm.vmid: vm for vm in db.query(VirtualMachine).filter(VirtualMachine.node_id == node.id).all()}
            found_vmids = set()
            
            for guest in guests:
                vmid = guest["vmid"]
                found_vmids.add(vmid)
                
                # Dati da salvare
                vm_data = {
                    "name": guest.get('name'),
                    "type": guest.get('type'),
                    "status": guest.get('status'),
                    "memory": guest.get('maxmem'),
                    "cpus": guest.get('cpus'),
                    "uptime": guest.get('uptime'),
                    "last_updated": datetime.utcnow()
                }
                
                if vmid in current_vms:
                    # Update
                    vm_obj = current_vms[vmid]
                    for k, v in vm_data.items():
                        if v is not None:
                            setattr(vm_obj, k, v)
                else:
                    # Create
                    new_vm = VirtualMachine(
                        node_id=node.id,
                        vmid=vmid,
                        **vm_data
                    )
                    db.add(new_vm)
            
            # Remove deleted VMs
            for vmid, vm_obj in current_vms.items():
                if vmid not in found_vmids:
                    db.delete(vm_obj)
            
            db.commit()
            logger.info(f"Updated {len(guests)} VMs for node {node.name}")
            
        except Exception as e:
            logger.error(f"Failed to refresh VMs for node {node.name}: {e}")
            db.rollback()
            # Non facciamo raise, permettiamo agli altri nodi di aggiornarsi
            # raise e

cache_service = CacheService()
