"""
Proxmox Service - Gestione VM e integrazione API Proxmox
"""

import asyncio
from typing import Optional, Dict, List, Tuple, Any
import logging
import json
import re

from services.ssh_service import ssh_service, SSHResult

logger = logging.getLogger(__name__)


class ProxmoxService:
    """Servizio per integrazione con Proxmox VE"""
    
    async def get_vm_list(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """Ottiene la lista delle VM (qemu) sul nodo"""
        
        result = await ssh_service.execute(
            hostname=hostname,
            command="qm list 2>/dev/null | tail -n +2",
            port=port,
            username=username,
            key_path=key_path
        )
        
        vms = []
        if result.success:
            for line in result.stdout.strip().split('\n'):
                if line:
                    # Format: VMID NAME STATUS MEM BOOTDISK PID
                    parts = line.split()
                    if len(parts) >= 3:
                        vms.append({
                            "vmid": int(parts[0]),
                            "name": parts[1],
                            "status": parts[2],
                            "type": "qemu"
                        })
        
        return vms
    
    async def get_container_list(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """Ottiene la lista dei container LXC sul nodo"""
        
        result = await ssh_service.execute(
            hostname=hostname,
            command="pct list 2>/dev/null | tail -n +2",
            port=port,
            username=username,
            key_path=key_path
        )
        
        containers = []
        if result.success:
            for line in result.stdout.strip().split('\n'):
                if line:
                    # Format: VMID STATUS LOCK NAME
                    parts = line.split()
                    if len(parts) >= 2:
                        containers.append({
                            "vmid": int(parts[0]),
                            "status": parts[1],
                            "name": parts[3] if len(parts) >= 4 else f"CT{parts[0]}",
                            "type": "lxc"
                        })
        
        return containers
    
    async def get_all_guests(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """Ottiene tutte le VM e i container"""
        vms = await self.get_vm_list(hostname, port, username, key_path)
        containers = await self.get_container_list(hostname, port, username, key_path)
        return vms + containers
    
    async def get_vm_config(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        cmd = "qm" if vm_type == "qemu" else "pct"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"{cmd} config {vmid}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        return result.success, result.stdout

    async def get_snapshots(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """Ottiene lista snapshot VM"""
        cmd_base = "qm" if vm_type == "qemu" else "pct"
        # qm listsnapshot <vmid> non ha output json nativo facile, ma proviamo a parsarle
        # Output tipico:
        # parent        pre-suspend     2023-01-01 10:00:00   description
        # current                                             
        
        # Purtroppo 'qm listsnapshot' è ostico da parsare.
        # Meglio usare config file parsing se possibile, ma qm listsnapshot mostra la struttura ad albero.
        # Per semplicità V2, usiamo lista piatta dai config o qm listsnapshot.
        
        # Usiamo pvesh che ha output json
        # pvesh get /nodes/{node}/qemu/{vmid}/snapshot --output-format json
        
        # Bisogna prima trovare il node name dal hostname?
        # get_snapshot usa SSH, pvesh richiede node name, non hostname (hostname network).
        # Se siamo su hostname, possiamo usare 'hostname' command per sapere il nome nodo, oppure assumiamo hostname ~= nodename
        # Oppure usiamo qm listsnapshot e parsiamo le righe.
        
        # Tentativo con pvesh assumendo esecuzione locale o che hostname corrisponda
        # Ma ssh_service esegue su 'hostname'.
        # Usiamo qm listsnapshot
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"{cmd_base} listsnapshot {vmid}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        snapshots = []
        if result.success:
            lines = result.stdout.strip().split('\n')
            # Skip header? qm listsnapshot header: "`name` `date/time` `parent` `description`?" NO
            # It prints a tree.
            # `current` line is the current state.
            
            for line in lines:
                if "`->`" in line or "current" in line:
                    # Tree view visualization characters handling might be complex
                    pass
                
                parts = line.split()
                if len(parts) >= 2:
                    # Very basic parsing
                    name = parts[0]
                    if name == "current": continue
                    
                    # Try to finding date info?
                    # This is unreliable. 
                    pass
        
        # Better approach: pvesh via SSH
        # We need the local nodename. 'uname -n' or 'hostname'.
        node_name_res = await ssh_service.execute(hostname, "hostname", port, username, key_path)
        node_name = node_name_res.stdout.strip() if node_name_res.success else "localhost"
        
        pvesh_cmd = f"pvesh get /nodes/{node_name}/{'qemu' if vm_type == 'qemu' else 'lxc'}/{vmid}/snapshot --output-format json"
        res = await ssh_service.execute(hostname, pvesh_cmd, port, username, key_path)
        
        if res.success and res.stdout.strip():
            try:
                snapshots = json.loads(res.stdout)
                # Filter 'current' entry usually returned
                snapshots = [s for s in snapshots if s.get('name') != 'current']
            except:
                pass
                
        return snapshots

    
    async def get_vm_config_file(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """Ottiene il file di configurazione raw della VM"""
        
        if vm_type == "qemu":
            config_path = f"/etc/pve/qemu-server/{vmid}.conf"
        else:
            config_path = f"/etc/pve/lxc/{vmid}.conf"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"cat {config_path}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        return result.success, result.stdout
    
    async def get_vm_disks_with_size(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """
        Ottiene tutti i dischi di una VM con dimensioni e dataset ZFS.
        Ritorna lista di dict con: disk_name, storage, volume, dataset, size, size_bytes
        """
        
        success, config = await self.get_vm_config(hostname, vmid, vm_type, port, username, key_path)
        
        if not success:
            return []
        
        # Pattern per dischi QEMU: scsi0: local-zfs:vm-100-disk-0,size=32G
        # Pattern per dischi LXC: mp0: local-zfs:subvol-100-disk-0,mp=/mnt/data,size=8G
        if vm_type == "qemu":
            disk_pattern = r'((?:scsi|sata|virtio|ide)\d+):\s*(\S+?):(\S+?)(?:,|$)'
        else:
            disk_pattern = r'((?:rootfs|mp)\d*):\s*(\S+?):(\S+?)(?:,|$)'
        
        matches = re.findall(disk_pattern, config)
        disks = []
        
        for disk_name, storage, volume in matches:
            # Ignora cdrom e cloudinit
            if 'cloudinit' in volume.lower() or 'none' in volume.lower():
                continue
            
            disk_info = {
                "disk_name": disk_name,
                "storage": storage,
                "volume": volume,
                "dataset": None,
                "size": "N/A",
                "size_bytes": 0
            }
            
            # Ottieni il path ZFS dello storage
            storage_result = await ssh_service.execute(
                hostname=hostname,
                command=f"pvesm path {storage}:{volume} 2>/dev/null",
                port=port,
                username=username,
                key_path=key_path
            )
            
            if storage_result.success and storage_result.stdout.strip():
                # Il path è tipo /dev/zvol/poolname/data/vm-100-disk-0
                # o /poolname/data/subvol-100-disk-0 per LXC
                path = storage_result.stdout.strip()
                
                # Estrai il dataset ZFS dal path
                if path.startswith('/dev/zvol/'):
                    dataset = path.replace('/dev/zvol/', '')
                elif path.startswith('/'):
                    # Per subvol LXC, cerca il dataset
                    dataset = path.lstrip('/')
                else:
                    dataset = None
                
                if dataset:
                    disk_info["dataset"] = dataset
                    
                    # Ottieni la dimensione del dataset/zvol
                    size_result = await ssh_service.execute(
                        hostname=hostname,
                        command=f"zfs get -Hp -o value used,volsize,referenced {dataset} 2>/dev/null | head -1",
                        port=port,
                        username=username,
                        key_path=key_path
                    )
                    
                    if size_result.success and size_result.stdout.strip():
                        try:
                            size_bytes = int(size_result.stdout.strip().split()[0])
                            disk_info["size_bytes"] = size_bytes
                            disk_info["size"] = self._format_size(size_bytes)
                        except:
                            pass
            
            disks.append(disk_info)
        
        return disks
    
    def _format_size(self, size_bytes: int) -> str:
        """Formatta dimensione in formato human-readable"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    async def get_node_bridges(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[str]:
        """Ottiene la lista dei bridge di rete disponibili sul nodo"""
        
        result = await ssh_service.execute(
            hostname=hostname,
            command="ip link show type bridge | grep -oP '(?<=: )vmbr[^:@]+' | sort -u",
            port=port,
            username=username,
            key_path=key_path
        )
        
        bridges = []
        if result.success and result.stdout.strip():
            bridges = [b.strip() for b in result.stdout.strip().split('\n') if b.strip()]
        
        return bridges

    async def get_node_cpu_info(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """Ottiene informazioni sulla CPU del nodo"""
        
        result = await ssh_service.execute(
            hostname=hostname,
            command="lscpu | grep -E 'Model name|Flags' | head -2",
            port=port,
            username=username,
            key_path=key_path
        )
        
        cpu_info = {
            "model": "Unknown",
            "supports_avx512": False,
            "supports_avx2": False
        }
        
        if result.success and result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                if 'Model name' in line:
                    cpu_info["model"] = line.split(':')[1].strip() if ':' in line else "Unknown"
                if 'Flags' in line:
                    flags = line.lower()
                    cpu_info["supports_avx512"] = 'avx512' in flags
                    cpu_info["supports_avx2"] = 'avx2' in flags
        
        return cpu_info

    async def get_vm_network_bridges(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[str]:
        """Ottiene i bridge di rete usati da una VM"""
        
        success, config = await self.get_vm_config(hostname, vmid, vm_type, port, username, key_path)
        
        if not success:
            return []
        
        # Cerca pattern: net0: virtio=...,bridge=vmbr0,...
        bridge_pattern = r'bridge=([^,\s]+)'
        bridges = re.findall(bridge_pattern, config)
        
        return list(set(bridges))

    async def get_vm_cpu_type(
        self,
        hostname: str,
        vmid: int,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> str:
        """Ottiene il tipo di CPU configurato per una VM"""
        
        success, config = await self.get_vm_config(hostname, vmid, "qemu", port, username, key_path)
        
        if not success:
            return "host"
        
        # Cerca pattern: cpu: x86-64-v4
        cpu_pattern = r'^cpu:\s*(.+)$'
        match = re.search(cpu_pattern, config, re.MULTILINE)
        
        return match.group(1).strip() if match else "host"

    async def find_vm_dataset(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[str]:
        """Trova i dataset ZFS associati a una VM"""
        
        # Prima ottieni la config per trovare gli storage
        success, config = await self.get_vm_config(hostname, vmid, vm_type, port, username, key_path)
        
        if not success:
            return []
        
        # Cerca pattern disco (es: scsi0: local-zfs:vm-100-disk-0,size=10241M)
        disk_pattern = r'(?:scsi|sata|virtio|ide|mp)\d+:\s*(\S+):(\S+)'
        disks = re.findall(disk_pattern, config)
        
        datasets = []
        
        for storage, disk_name_raw in disks:
            # Rimuovi parametri extra dopo la virgola (es: ,size=10241M)
            disk_name = disk_name_raw.split(',')[0]
            dataset_found = False
            
            # Trova il path ZFS dello storage
            result = await ssh_service.execute(
                hostname=hostname,
                command=f"pvesm status -storage {storage} 2>/dev/null | grep -E 'zfspool|dir'",
                port=port,
                username=username,
                key_path=key_path
            )
            
            if result.success and "zfspool" in result.stdout:
                # È uno storage ZFS, trova il dataset
                result2 = await ssh_service.execute(
                    hostname=hostname,
                    command=f"pvesm path {storage}:{disk_name} 2>/dev/null",
                    port=port,
                    username=username,
                    key_path=key_path
                )
                
                if result2.success:
                    # Output format: /dev/zvol/rpool/data/vm-100-disk-0
                    path = result2.stdout.strip()
                    if path.startswith("/dev/zvol/"):
                        dataset = path.replace("/dev/zvol/", "")
                        datasets.append(dataset)
                        dataset_found = True
                    elif path.startswith("/"):
                        # Potrebbe essere un dataset montato
                        result3 = await ssh_service.execute(
                            hostname=hostname,
                            command=f"zfs list -H -o name {path} 2>/dev/null",
                            port=port,
                            username=username,
                            key_path=key_path
                        )
                        if result3.success:
                            datasets.append(result3.stdout.strip())
                            dataset_found = True
            
            # Fallback: se lo storage non è registrato o non trovato, cerca direttamente il dataset ZFS
            if not dataset_found:
                # Cerca dataset che corrispondono al nome del disco (es: vm-667-disk-0)
                result_fallback = await ssh_service.execute(
                    hostname=hostname,
                    command=f"zfs list -H -o name 2>/dev/null | grep -E '{disk_name}$|/{disk_name}$' | head -5",
                    port=port,
                    username=username,
                    key_path=key_path
                )
                if result_fallback.success and result_fallback.stdout.strip():
                    for line in result_fallback.stdout.strip().split('\n'):
                        if line.strip() and line.strip() not in datasets:
                            datasets.append(line.strip())
        
        # Aggiungi anche il parent dataset se esiste (es: rpool/data)
        if datasets:
            parent = "/".join(datasets[0].split("/")[:-1])
            if parent and parent not in datasets:
                # Verifica se il parent contiene subvol per la VM
                result = await ssh_service.execute(
                    hostname=hostname,
                    command=f"zfs list -r -H -o name {parent} 2>/dev/null | grep -E 'vm-{vmid}|subvol-{vmid}'",
                    port=port,
                    username=username,
                    key_path=key_path
                )
                if result.success:
                    for line in result.stdout.strip().split('\n'):
                        if line and line not in datasets:
                            datasets.append(line)
        
        return list(set(datasets))
    
    async def ensure_zfs_storage(
        self,
        hostname: str,
        storage_name: str,
        zfs_pool: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Verifica/crea uno storage ZFS in Proxmox.
        Necessario per registrare VM con dischi in dataset personalizzati.
        """
        
        # Verifica se lo storage esiste già
        check_cmd = f"pvesm status -storage {storage_name} 2>/dev/null"
        result = await ssh_service.execute(
            hostname=hostname,
            command=check_cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and storage_name in result.stdout:
            return True, f"Storage {storage_name} già esistente"
        
        # Crea lo storage ZFS
        # Il formato del pool può essere "pool" o "pool/dataset"
        create_cmd = f"pvesm add zfspool {storage_name} --pool {zfs_pool} --content images,rootdir --sparse 1"
        result = await ssh_service.execute(
            hostname=hostname,
            command=create_cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success or "already exists" in result.stderr:
            return True, f"Storage {storage_name} creato/verificato"
        else:
            return False, f"Errore creazione storage: {result.stderr}"

    async def register_vm(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "qemu",
        config_content: Optional[str] = None,
        source_storage: Optional[str] = None,
        dest_storage: Optional[str] = None,
        dest_zfs_pool: Optional[str] = None,
        vm_name_suffix: Optional[str] = None,
        new_name: Optional[str] = None,  # Override completo del nome
        force_cpu_host: bool = True,
        dest_node_bridges: Optional[List[str]] = None,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str, List[str]]:
        """
        Registra una VM replicata su Proxmox
        
        Se config_content è fornito, crea il file di configurazione.
        Se dest_storage è specificato, sostituisce lo storage nella config.
        Se dest_zfs_pool è specificato, crea lo storage se non esiste.
        Se vm_name_suffix è specificato, aggiunge il suffisso al nome della VM.
        Se new_name è specificato, imposta il nome della VM (sovrascrive suffix).
        Se force_cpu_host è True, cambia il tipo CPU a 'host'.
        
        Ritorna: (success, message, warnings)
        """
        warnings = []
        
        if vm_type == "qemu":
            config_path = f"/etc/pve/qemu-server/{vmid}.conf"
        else:
            config_path = f"/etc/pve/lxc/{vmid}.conf"
        
        # Verifica che il VMID non sia già in uso
        check_cmd = f"qm status {vmid} 2>/dev/null || pct status {vmid} 2>/dev/null"
        result = await ssh_service.execute(
            hostname=hostname,
            command=check_cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and ("status:" in result.stdout or "running" in result.stdout or "stopped" in result.stdout):
            return False, f"VMID {vmid} già in uso su questo nodo", []
        
        # Se abbiamo un dest_storage e dest_zfs_pool, creiamo/verifichiamo lo storage
        if dest_storage and dest_zfs_pool:
            storage_ok, storage_msg = await self.ensure_zfs_storage(
                hostname=hostname,
                storage_name=dest_storage,
                zfs_pool=dest_zfs_pool,
                port=port,
                username=username,
                key_path=key_path
            )
            if not storage_ok:
                return False, f"Errore storage: {storage_msg}", []
        
        if config_content:
            import re
            
            # Se abbiamo source_storage e dest_storage, sostituisci nella config
            if source_storage and dest_storage and source_storage != dest_storage:
                # Sostituisci il nome dello storage (es: local-zfs: -> replica-storage:)
                config_content = config_content.replace(f"{source_storage}:", f"{dest_storage}:")
            
            # Gestione Nome VM
            name_pattern = re.compile(r'^(name:\s*)(.+)$', re.MULTILINE)
            match = name_pattern.search(config_content)
            
            final_name = None
            original_name = None
            
            if match:
                original_name = match.group(2).strip()
            
            if new_name:
                final_name = new_name
            elif original_name and vm_name_suffix:
                # Original name exists, add suffix
                final_name = original_name + vm_name_suffix
            elif original_name:
                # Original name exists, no suffix requested
                final_name = original_name
            elif vm_name_suffix:
                # No original name found - this should not happen for valid VMs
                # Use a descriptive name instead of just ID
                final_name = f"replica-vm-{vmid}{vm_name_suffix}"
                warnings.append(f"Nome originale non trovato; assegnato nome: {final_name}")
            
            if final_name:
                # Sanitize name: replace underscores with dashes for compatibility
                final_name = final_name.replace('_', '-')

                if match:
                    # Sostituisci linea esistente
                    config_content = name_pattern.sub(f'name: {final_name}', config_content)
                else:
                    # Aggiungi linea nome all'inizio
                    config_content = f"name: {final_name}\n" + config_content
            
            # Forza CPU type a 'host' per compatibilità tra host diversi
            if force_cpu_host and vm_type == "qemu":
                cpu_pattern = re.compile(r'^cpu:\s*.+$', re.MULTILINE)
                if cpu_pattern.search(config_content):
                    old_cpu = cpu_pattern.search(config_content).group(0)
                    config_content = cpu_pattern.sub('cpu: host', config_content)
                    warnings.append(f"CPU cambiata da '{old_cpu}' a 'cpu: host' per compatibilità")
            
            # Verifica bridge di rete
            if dest_node_bridges:
                net_pattern = re.compile(r'^(net\d+):.+bridge=([^,\s]+)', re.MULTILINE)
                for match in net_pattern.finditer(config_content):
                    net_iface = match.group(1)
                    bridge = match.group(2)
                    if bridge not in dest_node_bridges:
                        warnings.append(f"⚠️ RETE: {net_iface} usa bridge '{bridge}' che non esiste sul nodo destinazione. Bridge disponibili: {', '.join(dest_node_bridges)}")
            
            # Crea il file di configurazione
            cmd = f"""
mkdir -p $(dirname {config_path})
cat > {config_path} << 'VMCONF_EOF'
{config_content}
VMCONF_EOF
echo "Configuration created"
"""
            result = await ssh_service.execute(
                hostname=hostname,
                command=cmd,
                port=port,
                username=username,
                key_path=key_path
            )
            
            if not result.success:
                return False, f"Errore creazione config: {result.stderr}", warnings
        
        # Verifica registrazione
        verify_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} status {vmid}"
        result = await ssh_service.execute(
            hostname=hostname,
            command=verify_cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            return True, f"VM {vmid} registrata con successo", warnings
        else:
            return False, f"Verifica fallita: {result.stderr}", warnings
    
    async def unregister_vm(
        self,
        hostname: str,
        vmid: int,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Rimuove la registrazione di una VM (senza eliminare i dati)
        """
        
        # Prima verifica che sia spenta
        cmd = "qm" if vm_type == "qemu" else "pct"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"{cmd} status {vmid}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if "running" in result.stdout:
            return False, "La VM deve essere spenta prima della rimozione"
        
        # Rimuovi solo il file config (non i dati)
        if vm_type == "qemu":
            config_path = f"/etc/pve/qemu-server/{vmid}.conf"
        else:
            config_path = f"/etc/pve/lxc/{vmid}.conf"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"rm -f {config_path}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            return True, f"VM {vmid} deregistrata (dati mantenuti)"
        return False, result.stderr
    
    async def get_next_vmid(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> int:
        """Ottiene il prossimo VMID disponibile"""
        
        result = await ssh_service.execute(
            hostname=hostname,
            command="pvesh get /cluster/nextid",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            try:
                return int(result.stdout.strip())
            except ValueError:
                pass
        
        # Fallback: trova manualmente
        result = await ssh_service.execute(
            hostname=hostname,
            command="(qm list 2>/dev/null; pct list 2>/dev/null) | awk '{print $1}' | sort -n | tail -1",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and result.stdout.strip():
            try:
                return int(result.stdout.strip()) + 1
            except ValueError:
                pass
        
        return 100  # Default
    
    async def get_vm_full_details(
        self,
        hostname: str,
        node_name: Optional[str] = None,
        vmid: int = 0,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, Any]:
        """
        Raccolta dettagli completi VM usando pvesh.
        Include: config, status, agent data, snapshots, IP addresses.
        Ispirato a Proxreporter.
        """
        result = {
            "vmid": vmid,
            "name": f"VM-{vmid}",
            "vm_type": vm_type,
            "status": "unknown",
            "config": {},
            "runtime": {},
            "disks": [],
            "networks": [],
            "ip_addresses": {"ipv4": [], "ipv6": [], "all": []},
            "snapshots": {"count": 0, "list": []},
            "agent": {"enabled": False, "version": None}
        }
        
        # Ottieni node name se non fornito
        if not node_name:
            cmd = "hostname"
            hostname_result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            node_name = hostname_result.stdout.strip() if hostname_result.success else hostname
        
        # Config via pvesh
        cmd = f"pvesh get /nodes/{node_name}/{vm_type}/{vmid}/config --output-format json 2>/dev/null"
        config_result = await ssh_service.execute(hostname, cmd, port, username, key_path)
        
        if config_result.success and config_result.stdout.strip():
            try:
                config_data = json.loads(config_result.stdout)
                result["config"] = config_data
                result["name"] = config_data.get("name", f"VM-{vmid}")
            except json.JSONDecodeError:
                logger.warning(f"Errore parsing config JSON per VM {vmid}")
        
        # Status via pvesh
        cmd = f"pvesh get /nodes/{node_name}/{vm_type}/{vmid}/status/current --output-format json 2>/dev/null"
        status_result = await ssh_service.execute(hostname, cmd, port, username, key_path)
        
        if status_result.success and status_result.stdout.strip():
            try:
                status_data = json.loads(status_result.stdout)
                result["status"] = status_data.get("status", "unknown")
                result["runtime"] = {
                    "cpu": status_data.get("cpu", 0),
                    "cpu_percent": status_data.get("cpu", 0),
                    "mem": status_data.get("mem", 0),
                    "mem_used_mb": status_data.get("mem", 0) / (1024 * 1024) if status_data.get("mem") else 0,
                    "maxmem": status_data.get("maxmem", 0),
                    "mem_total_mb": status_data.get("maxmem", 0) / (1024 * 1024) if status_data.get("maxmem") else 0,
                    "uptime": status_data.get("uptime", 0),
                    "uptime_seconds": status_data.get("uptime", 0),
                    "diskread": status_data.get("diskread", 0),
                    "diskread_bytes": status_data.get("diskread", 0),
                    "diskwrite": status_data.get("diskwrite", 0),
                    "diskwrite_bytes": status_data.get("diskwrite", 0),
                    "netin": status_data.get("netin", 0),
                    "netin_bytes": status_data.get("netin", 0),
                    "netout": status_data.get("netout", 0),
                    "netout_bytes": status_data.get("netout", 0),
                    "balloon": status_data.get("balloon", 0),
                    "balloon_mb": status_data.get("balloon", 0) / (1024 * 1024) if status_data.get("balloon") else 0,
                    "pid": status_data.get("pid"),
                    "qmpstatus": status_data.get("qmpstatus"),
                    "ha_state": status_data.get("ha", {}).get("state") if isinstance(status_data.get("ha"), dict) else None
                }
                
                # Agent info - può essere int (1/0), bool, o dict
                agent_data = status_data.get("agent")
                if agent_data:
                    if isinstance(agent_data, dict):
                        result["agent"] = {
                            "enabled": True,
                            "version": agent_data.get("version"),
                            "status": agent_data.get("status")
                        }
                    else:
                        # agent è un int o bool
                        result["agent"] = {
                            "enabled": bool(agent_data),
                            "version": None
                        }
            except json.JSONDecodeError:
                logger.warning(f"Errore parsing status JSON per VM {vmid}")
        
        # Controlla anche dalla config se agent è abilitato
        if result["config"].get("agent") and not result["agent"].get("enabled"):
            agent_config = result["config"].get("agent", "0")
            result["agent"]["enabled"] = str(agent_config).startswith("1")
        
        # Agent network (se running e agent abilitato)
        if result["status"] == "running" and result["agent"].get("enabled"):
            cmd = f"pvesh get /nodes/{node_name}/{vm_type}/{vmid}/agent/network-get-interfaces --output-format json 2>/dev/null"
            agent_network_result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if agent_network_result.success and agent_network_result.stdout.strip():
                try:
                    agent_network_data = json.loads(agent_network_result.stdout)
                    interfaces = agent_network_data.get("result", []) if isinstance(agent_network_data, dict) else agent_network_data
                    
                    ipv4_list = []
                    ipv6_list = []
                    all_ips = []
                    
                    for iface in interfaces if isinstance(interfaces, list) else []:
                        ip_addresses = iface.get("ip-addresses", []) or iface.get("ip_addresses", [])
                        for ip_entry in ip_addresses:
                            if isinstance(ip_entry, dict):
                                ip_value = ip_entry.get("ip-address") or ip_entry.get("ip") or ""
                                if ip_value and ip_value not in ["127.0.0.1", "::1"]:
                                    all_ips.append(ip_value)
                                    if ":" in ip_value:
                                        ipv6_list.append(ip_value)
                                    else:
                                        ipv4_list.append(ip_value)
                    
                    result["ip_addresses"] = {
                        "ipv4": sorted(set(ipv4_list)),
                        "ipv6": sorted(set(ipv6_list)),
                        "all": sorted(set(all_ips))
                    }
                except json.JSONDecodeError:
                    logger.warning(f"Errore parsing agent network JSON per VM {vmid}")
        
        # Snapshots via pvesh
        cmd = f"pvesh get /nodes/{node_name}/{vm_type}/{vmid}/snapshot --output-format json 2>/dev/null"
        snapshots_result = await ssh_service.execute(hostname, cmd, port, username, key_path)
        
        if snapshots_result.success and snapshots_result.stdout.strip():
            try:
                snapshots_data = json.loads(snapshots_result.stdout)
                snapshots_list = snapshots_data.get("data", []) if isinstance(snapshots_data, dict) else snapshots_data
                
                snapshots = []
                for snap in snapshots_list if isinstance(snapshots_list, list) else []:
                    if isinstance(snap, dict):
                        snapshots.append({
                            "name": snap.get("name"),
                            "snaptime": snap.get("snaptime"),
                            "description": snap.get("description"),
                            "parent": snap.get("parent"),
                            "vmstate": snap.get("vmstate")
                        })
                
                result["snapshots"] = {
                    "count": len(snapshots),
                    "list": snapshots
                }
            except json.JSONDecodeError:
                logger.warning(f"Errore parsing snapshots JSON per VM {vmid}")
        
        # Networks dalla config
        if result["config"]:
            networks = []
            for key, value in result["config"].items():
                if key.startswith("net") and isinstance(value, str):
                    # Parse network config: model=XX,bridge=vmbr0,...
                    net_info = {"id": key, "raw": value}
                    for part in value.split(","):
                        if "=" in part:
                            param, param_value = part.split("=", 1)
                            net_info[param.strip()] = param_value.strip()
                    networks.append(net_info)
            result["networks"] = networks
        
        # Dischi (usa metodo esistente e arricchisci con info dalla config)
        disks = await self.get_vm_disks_with_size(
            hostname=hostname,
            vmid=vmid,
            vm_type=vm_type,
            port=port,
            username=username,
            key_path=key_path
        )
        
        # Arricchisci dischi con info dalla config
        if result["config"]:
            for disk in disks:
                disk_id = disk.get("disk_name", "").replace(":", "")
                # Cerca nella config per questo disco
                for key, value in result["config"].items():
                    if key == disk_id or key.startswith(disk_id + ":"):
                        # Parse parametri aggiuntivi
                        if isinstance(value, str):
                            for param in value.split(","):
                                if "=" in param:
                                    param_name, param_value = param.split("=", 1)
                                    param_name = param_name.strip()
                                    param_value = param_value.strip()
                                    
                                    if param_name == "discard":
                                        disk["discard"] = param_value
                                    elif param_name == "iothread":
                                        disk["iothread"] = param_value
                                    elif param_name == "media":
                                        disk["media"] = param_value
                                    elif param_name == "size":
                                        disk["size_config"] = param_value
                
                # Imposta tipo e ID
                disk["id"] = disk.get("disk_name", "").replace(":", "")
                disk["type"] = "disk"
                if not disk.get("volume"):
                    disk["volume"] = disk.get("dataset", "none")
        
        result["disks"] = disks
        
        # Parse config per info aggiuntive
        if result["config"]:
            # CPU info
            cores = result["config"].get("cores")
            sockets = result["config"].get("sockets")
            if cores and sockets:
                result["config"]["maxcpu"] = int(cores) * int(sockets)
            
            # Memory info
            memory = result["config"].get("memory")
            if memory:
                try:
                    result["config"]["memory_mb"] = int(memory)
                    result["config"]["memory_gb"] = round(int(memory) / 1024, 2)
                except (ValueError, TypeError):
                    pass
            
            # Estrai info aggiuntive dalla config
            result["bios"] = result["config"].get("bios", "seabios")
            result["ostype"] = result["config"].get("ostype", "l26")
            result["boot"] = result["config"].get("boot", "")
            
            # Agent info - converti in dizionario per compatibilità con il modello
            agent_config = result["config"].get("agent", "0")
            agent_enabled = agent_config == "1" or str(agent_config).startswith("1")
            result["agent"] = {
                "enabled": agent_enabled,
                "version": None
            }
            result["agent_enabled"] = agent_enabled
            result["tags"] = result["config"].get("tags", "")
            
            # Primary bridge (prima interfaccia di rete)
            if result["networks"] and len(result["networks"]) > 0:
                primary_net = result["networks"][0]
                result["primary_bridge"] = primary_net.get("bridge", "")
            else:
                result["primary_bridge"] = ""
            
            # Primary IP (dal runtime se disponibile)
            if result["ip_addresses"] and result["ip_addresses"].get("ipv4"):
                result["primary_ip"] = result["ip_addresses"]["ipv4"][0]
            else:
                result["primary_ip"] = ""
        
        return result


    async def get_cluster_resources(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """
        Ottiene risorse cluster (VM, CT) con dettagli su nodo e stato.
        Usa pvesh per ottenere dati aggregati dal cluster.
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="pvesh get /cluster/resources --output-format json 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path
        )
        
        resources = []
        if result.success and result.stdout.strip():
            try:
                resources = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.error(f"Errore parsing cluster resources da {hostname}")
        
        return resources

    async def vm_lifecycle_action(
        self,
        hostname: str,
        vmid: int,
        action: str,  # start, stop, shutdown, reboot, resume, suspend
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """Esegue azione lifecycle su VM"""
        
        cmd_base = "qm" if vm_type == "qemu" else "pct"
        cmd = f"{cmd_base} {action} {vmid}"
        
        # Per stop forzato, aggiungi extra flags se necessario, ma qm stop è safe
        # Per reboot qemu potrebbe servire --timeout
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=120
        )
        
        if result.success:
            return True, f"Azione {action} su VM {vmid} avviata"
        else:
            return False, f"Errore {action}: {result.stderr}"

    async def create_snapshot(
        self,
        hostname: str,
        vmid: int,
        snapname: str,
        description: str = "",
        vmstate: bool = False,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """Crea snapshot VM"""
        
        cmd_base = "qm" if vm_type == "qemu" else "pct"
        cmd = f"{cmd_base} snapshot {vmid} {snapname}"
        if description:
            cmd += f" --description \"{description}\""
        if vmstate and vm_type == "qemu":
            cmd += " --vmstate 1"
            
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=300
        )
        
        if result.success:
            return True, "Snapshot creato con successo"
        else:
            return False, f"Errore snapshot: {result.stderr}"

    async def rollback_snapshot(
        self,
        hostname: str,
        vmid: int,
        snapname: str,
        start_vm: bool = False,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """Rollback snapshot VM"""
        
        cmd_base = "qm" if vm_type == "qemu" else "pct"
        cmd = f"{cmd_base} rollback {vmid} {snapname}"
        if start_vm:
            cmd += " --start 1"
            
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=300
        )
        
        if result.success:
            return True, "Rollback completato"
        else:
            return False, f"Errore rollback: {result.stderr}"

    async def delete_snapshot(
        self,
        hostname: str,
        vmid: int,
        snapname: str,
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """Elimina snapshot VM"""
        
        cmd_base = "qm" if vm_type == "qemu" else "pct"
        cmd = f"{cmd_base} delsnapshot {vmid} {snapname}"
            
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=300
        )
        
        if result.success:
            return True, "Snapshot eliminato"
        else:
            return False, f"Errore eliminazione: {result.stderr}"

    async def clone_vm_from_zfs_snapshot(
        self,
        hostname: str,
        source_vmid: int,
        new_vmid: int,
        snapshot_name: str,
        datasets: List[str],
        vm_type: str = "qemu",
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Clona una VM da snapshot ZFS creando una nuova VM indipendente.
        """
        # 1. Verifica disponibilità ID
        check_cmd = f"qm status {new_vmid} 2>/dev/null || pct status {new_vmid} 2>/dev/null"
        res = await ssh_service.execute(hostname, check_cmd, port, username, key_path)
        if "running" in res.stdout or "stopped" in res.stdout or "unknown" in res.stdout:
             # "unknown" in output often means "qm: VM 100 not running" but exits 0 or similar.
             # Better check: if output contains "status:", it exists.
             if "status:" in res.stdout:
                 return False, f"VMID {new_vmid} già esistente"

        # 2. Costruisci script di cloning
        # Logica: 
        # - Leggi config originale
        # - Per ogni dataset ZFS, esegui clone
        # - Crea nuova config con path aggiornati
        
        config_path_src = f"/etc/pve/qemu-server/{source_vmid}.conf" if vm_type == "qemu" else f"/etc/pve/lxc/{source_vmid}.conf"
        config_path_dst = f"/etc/pve/qemu-server/{new_vmid}.conf" if vm_type == "qemu" else f"/etc/pve/lxc/{new_vmid}.conf"
        
        # Script bash complesso
        script = f"""
set -e

# 1. Verification
if [ -f "{config_path_dst}" ]; then
    echo "Error: Config {config_path_dst} already exists"
    exit 1
fi

# 2. Clone Datasets
"""
        
        # Mappa dataset src -> dst
        cloned_disks = []
        
        for ds in datasets:
            # Assumiamo naming convention standard: .../vm-SOURCEID-disk-X
            # Sostituiamo SOURCEID con NEWID
            if str(source_vmid) in ds:
                new_ds = ds.replace(str(source_vmid), str(new_vmid))
                # Comando clone
                script += f"echo 'Cloning {ds}@{snapshot_name} to {new_ds}...'\n"
                script += f"zfs clone -p {ds}@{snapshot_name} {new_ds}\n"
                cloned_disks.append((ds, new_ds))
            else:
                # Fallback: appendi NEWID
                new_ds = f"{ds}-clone-{new_vmid}"
                script += f"echo 'Cloning {ds}@{snapshot_name} to {new_ds} (fallback name)...'\n"
                script += f"zfs clone -p {ds}@{snapshot_name} {new_ds}\n"
                cloned_disks.append((ds, new_ds))

        # 3. Clone Config
        # Leggi config src, sostituisci ID nei path dei dischi
        script += f"""
echo 'Generating config...'
cat {config_path_src} > {config_path_dst}.tmp

# Rimuovi righe lock, parent, snaptime
sed -i '/^lock:/d' {config_path_dst}.tmp
sed -i '/^parent:/d' {config_path_dst}.tmp
sed -i '/^snaptime:/d' {config_path_dst}.tmp
sed -i '/^vmstate:/d' {config_path_dst}.tmp

# Sostituisci i dataset paths
"""
        for src, dst in cloned_disks:
            # Escape slashes per sed
            src_esc = src.replace('/', '\\/')
            dst_esc = dst.replace('/', '\\/')
            # Per i volumi ZFS, Proxmox usa storage:vm-ID-disk-X
            # Ma nella config sottostante il path potrebbe non apparire esplicitamente se usa storage plugin.
            # Tuttavia, se è ZFS, il nome volume cambia da vm-OLD-disk-X a vm-NEW-disk-X
            # Basta sostituire vm-OLD-disk con vm-NEW-disk globalmente?
            # Sì, di solito safe.
            pass
            
        # Sostituzione generica ID
        script += f"sed -i 's/vm-{source_vmid}-/vm-{new_vmid}-/g' {config_path_dst}.tmp\n"
        script += f"sed -i 's/subvol-{source_vmid}-/subvol-{new_vmid}-/g' {config_path_dst}.tmp\n"
        
        # Rigenera MAC address per evitare conflitti
        # Rimuovi le righe net per semplicità o prova a rigenerare?
        # Meglio lasciare net ma cambiare MAC. 
        # Sed regex per mac: XX:XX:XX...
        # Semplice: rimuovi net config? No, l'utente perde la rete.
        # Lasciamo MAC uguale? No, conflitto.
        # Soluzione: Rimuovi parametru mac=... dalla riga net?
        script += "sed -i -E 's/mac=[0-9A-Fa-f:]+,?//g' " + f"{config_path_dst}.tmp\n"
        
        # Sposta config finale
        script += f"mv {config_path_dst}.tmp {config_path_dst}\n"
        script += "echo 'Done.'\n"
        
        # Execute
        res = await ssh_service.execute(hostname, script, port, username, key_path, timeout=300)
        
        if res.success:
            return True, f"Clone creato con successo: VM {new_vmid}"
        else:
            return False, f"Errore durant cloning: {res.stderr}"

# Singleton
proxmox_service = ProxmoxService()
