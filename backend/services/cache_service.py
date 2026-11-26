from sqlalchemy.orm import Session
from datetime import datetime
import logging
import asyncio

from database import Node, VirtualMachine, NodeType
from services.proxmox_service import proxmox_service
from services.pbs_service import pbs_service

logger = logging.getLogger(__name__)

# Dopo quanti giri senza risposta un nodo viene segnato non in linea. Un giro
# solo e' spesso un singhiozzo di rete: `is_online` lo leggono il login e lo
# scheduler, e non deve ballare.
GIRI_MUTI_PER_OFFLINE = 3


class CacheService:
    def __init__(self):
        self._giri_muti: dict = {}

    def _segna_esito(self, node: Node, ha_risposto: bool) -> None:
        """Aggiorna `is_online`/`last_check` dal giro periodico (3.26.0).

        Prima li scriveva solo il «Test» a mano: a Domarc erano fermi ad aprile.
        """
        if ha_risposto:
            self._giri_muti.pop(node.id, None)
            node.is_online = True
            node.last_check = datetime.utcnow()
            return
        muti = self._giri_muti.get(node.id, 0) + 1
        self._giri_muti[node.id] = muti
        if muti >= GIRI_MUTI_PER_OFFLINE and node.is_online:
            logger.warning(f"Nodo {node.name}: {muti} giri senza risposta, segnato non in linea")
            node.is_online = False

    @staticmethod
    async def _porta_aperta(host: str, porta: int, attesa: float = 3.0) -> bool:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(host, porta), attesa)
        except (OSError, asyncio.TimeoutError):
            return False
        w.close()
        return True

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
                
                # Cache inventario PBS: gestita in pbs_service (TTL 5 min)
                
                results[node.name] = "OK"
            except Exception as e:
                logger.error(f"Error refreshing node {node.name}: {e}")
                results[node.name] = str(e)
        
        logger.info("Cache refresh completed")
        return results

    async def refresh_node_vms(self, db: Session, node: Node):
        """Aggiorna cache VM e dettagli Host per un singolo nodo"""
        # Un nodo già segnato non in linea si riprova solo se la porta ssh
        # risponde: a DTS un PBS con l'indirizzo cambiato ha scritto due errori
        # ogni 5 minuti per tre settimane (26/11/2026).
        if not node.is_online and not node.is_auth_node:
            if not await self._porta_aperta(node.hostname, node.ssh_port or 22):
                logger.debug(f"Nodo {node.name} ancora non raggiungibile: giro saltato")
                return

        try:
            # 1. Aggiorna Host Info (Advanced Data)
            # Utilizza host_info_service per raccogliere metriche avanzate (CPU, RAM specifica, Storage, Network)
            from services.host_info_service import HostInfoService
            host_service = HostInfoService()
            # Nota: update_host_details crea la sua sessione, quindi è autonomo
            dettagli = await host_service.update_host_details(node.id)

            # Un PBS non ospita VM: chiedergli le risorse del cluster dava solo
            # un avviso a ogni giro (~1900 a settimana a Domarc, 24/11/2026).
            # Il suo stato «in linea» viene dalla raccolta dei dati host: prima
            # non lo aggiornava nessuno e un PBS irraggiungibile restava «in
            # linea» (DTS2-PBS, 26/11/2026).
            if node.node_type == NodeType.PBS.value:
                from services.host_info_service import ha_risposto as host_ha_risposto
                self._segna_esito(node, host_ha_risposto(dettagli))
                db.commit()
                return

            logger.debug(f"Fetching Cluster Resources for node {node.name}")
            
            # 2. Ottieni lista VM/CT con metriche avanzate (via pvesh cluster resource)
            # Questo ritorna CPU usage, MaxMem, Uptime, etc.
            ha_risposto, resources = await proxmox_service.get_cluster_resources_esito(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            self._segna_esito(node, ha_risposto)
            if not ha_risposto:
                # Niente risposta non vuol dire «niente VM»: prima l'elenco vuoto
                # faceva cancellare dalla cache tutte le VM del nodo (3.26.0).
                db.commit()
                logger.warning(f"Nodo {node.name} non ha risposto: cache VM lasciata com'e'")
                return
            
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
            
            # Remove deleted VMs. Se l'elenco viene dal ripiego `qm list` ed e'
            # vuoto mentre in cache ce ne sono, non si sa se sono sparite o se
            # il ripiego ha fallito: non si cancella.
            if guests or node_resources or not current_vms:
                for vmid, vm_obj in current_vms.items():
                    if vmid not in found_vmids:
                        db.delete(vm_obj)
            else:
                logger.warning(f"Nodo {node.name}: elenco VM vuoto dal ripiego, cache lasciata com'e'")
            db.commit()
            logger.info(f"Updated {len(guests)} VMs for node {node.name}")
            
        except Exception as e:
            logger.error(f"Failed to refresh VMs for node {node.name}: {e}")
            db.rollback()
            # Non facciamo raise, permettiamo agli altri nodi di aggiornarsi
            # raise e

cache_service = CacheService()
