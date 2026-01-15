"""
SSH Service - Gestione connessioni SSH ai nodi Proxmox
"""

import asyncio
import paramiko
from typing import Optional, Tuple, List, Dict
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SSHResult:
    """Risultato di un comando SSH"""
    success: bool
    stdout: str
    stderr: str
    exit_code: int


from pathlib import Path

class SSHService:
    """Servizio per eseguire comandi via SSH sui nodi Proxmox"""
    
    DEFAULT_KEY_PATH = str(Path.home() / ".ssh" / "id_rsa")

    def __init__(self):
        self._connections: Dict[str, paramiko.SSHClient] = {}
        # Override se siamo root
        if os.geteuid() == 0:
            self.DEFAULT_KEY_PATH = "/root/.ssh/id_rsa"
    
    def _get_client(
        self, 
        hostname: str, 
        port: int = 22,
        username: str = "root",
        key_path: str = None
    ) -> paramiko.SSHClient:
        """Ottiene o crea una connessione SSH"""
        key_path = key_path or self.DEFAULT_KEY_PATH
        key = f"{username}@{hostname}:{port}"
        
        if key in self._connections:
            client = self._connections[key]
            # Verifica se la connessione è ancora attiva
            try:
                transport = client.get_transport()
                if transport and transport.is_active():
                    return client
            except:
                pass
            # Connessione non attiva, la rimuoviamo
            del self._connections[key]
        
        # Crea nuova connessione
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            client.connect(
                hostname=hostname,
                port=port,
                username=username,
                key_filename=key_path,
                timeout=10,
                banner_timeout=10
            )
            self._connections[key] = client
            return client
        except Exception as e:
            logger.error(f"Errore connessione SSH a {hostname}: {e}")
            raise
    
    async def execute(
        self,
        hostname: str,
        command: str,
        port: int = 22,
        username: str = "root",
        key_path: str = None,
        timeout: int = 300
    ) -> SSHResult:
        """Esegue un comando su un nodo remoto"""
        key_path = key_path or self.DEFAULT_KEY_PATH
        def _execute():
            try:
                client = self._get_client(hostname, port, username, key_path)
                stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
                
                exit_code = stdout.channel.recv_exit_status()
                stdout_text = stdout.read().decode('utf-8', errors='replace')
                stderr_text = stderr.read().decode('utf-8', errors='replace')
                
                return SSHResult(
                    success=(exit_code == 0),
                    stdout=stdout_text,
                    stderr=stderr_text,
                    exit_code=exit_code
                )
            except Exception as e:
                logger.error(f"Errore esecuzione comando su {hostname}: {e}")
                return SSHResult(
                    success=False,
                    stdout="",
                    stderr=str(e),
                    exit_code=-1
                )
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _execute)
    
    async def test_connection(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = None
    ) -> Tuple[bool, str]:
        """Testa la connessione a un nodo"""
        key_path = key_path or self.DEFAULT_KEY_PATH
        result = await self.execute(
            hostname=hostname,
            command="echo 'OK' && hostname",
            port=port,
            username=username,
            key_path=key_path,
            timeout=10
        )
        
        if result.success:
            return True, result.stdout.strip()
        return False, result.stderr
    
    async def check_sanoid_installed(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = None
    ) -> Tuple[bool, Optional[str]]:
        """Verifica se Sanoid è installato"""
        key_path = key_path or self.DEFAULT_KEY_PATH
        # Check in common paths in case it's not in PATH
        # Redirect output of version to stdout
        cmd = "export PATH=$PATH:/usr/sbin:/usr/local/sbin:/sbin; if which sanoid >/dev/null; then sanoid --version 2>&1; else echo 'not found'; fi"
        
        result = await self.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and "not found" not in result.stdout:
            output = result.stdout.strip()
            if output:
                lines = output.split('\n')
                version = "Installed"
                
                # Scan lines for "sanoid version X.Y.Z"
                import re
                for line in lines:
                    # Skip lines that look like Perl module versions (e.g. "(Getopt::Long...)")
                    if line.strip().startswith('(') or 'Perl version' in line:
                        continue
                        
                    match = re.search(r'sanoid version\s+v?([0-9.]+)', line, re.IGNORECASE)
                    if match:
                        version = match.group(1)
                        break
                else:
                    # Fallback: take the first valid-looking line if regex fails
                    for line in lines:
                        if line.strip() and not line.strip().startswith('(') and 'Perl version' not in line:
                             version = line.strip()
                             break
                        
                return True, version
            return True, "Installed"
        return False, None
    
    async def get_zfs_datasets(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = None
    ) -> List[Dict]:
        """Ottiene la lista dei dataset ZFS"""
        key_path = key_path or self.DEFAULT_KEY_PATH
        result = await self.execute(
            hostname=hostname,
            command="zfs list -H -o name,used,avail,mountpoint -t filesystem,volume",
            port=port,
            username=username,
            key_path=key_path
        )
        
        datasets = []
        if result.success:
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 4:
                        datasets.append({
                            "name": parts[0],
                            "used": parts[1],
                            "available": parts[2],
                            "mountpoint": parts[3] if parts[3] != "-" else None
                        })
        return datasets
    
    async def get_snapshots(
        self,
        hostname: str,
        dataset: Optional[str] = None,
        port: int = 22,
        username: str = "root",
        key_path: str = None
    ) -> List[Dict]:
        """Ottiene la lista degli snapshot ZFS"""
        key_path = key_path or self.DEFAULT_KEY_PATH
        cmd = "zfs list -H -t snapshot -o name,used,creation -s creation"
        if dataset:
            cmd += f" -r {dataset}"
        
        result = await self.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        snapshots = []
        if result.success:
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 3:
                        name_parts = parts[0].split('@')
                        snapshots.append({
                            "full_name": parts[0],
                            "dataset": name_parts[0] if len(name_parts) > 0 else "",
                            "snapshot": name_parts[1] if len(name_parts) > 1 else "",
                            "used": parts[1],
                            "creation": parts[2]
                        })
        return snapshots
    
    async def create_snapshot(
        self,
        hostname: str,
        dataset: str,
        snapshot_name: str,
        recursive: bool = False,
        port: int = 22,
        username: str = "root",
        key_path: str = None
    ) -> SSHResult:
        """Crea uno snapshot manuale"""
        key_path = key_path or self.DEFAULT_KEY_PATH
        r_flag = "-r" if recursive else ""
        cmd = f"zfs snapshot {r_flag} {dataset}@{snapshot_name}"
        
        return await self.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
    
    async def delete_snapshot(
        self,
        hostname: str,
        full_snapshot_name: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> SSHResult:
        """Elimina uno snapshot"""
        cmd = f"zfs destroy {full_snapshot_name}"
        
        return await self.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
    
    async def read_remote_file(
        self,
        hostname: str,
        remote_path: str,
        port: int = 22,
        username: str = "root",
        key_path: str = None
    ) -> Optional[bytes]:
        """Legge un file remoto in binario usando SFTP"""
        key_path = key_path or self.DEFAULT_KEY_PATH
        
        def _read():
            client = None
            sftp = None
            try:
                client = self._get_client(hostname, port, username, key_path)
                sftp = client.open_sftp()
                with sftp.open(remote_path, 'rb') as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Errore lettura file remoto {hostname}:{remote_path}: {e}")
                return None
            finally:
                if sftp:
                    sftp.close()
                # Non chiudiamo il client perché è gestito dal pool _connections
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _read)

    
    def close_all(self):
        """Chiude tutte le connessioni"""
        for key, client in self._connections.items():
            try:
                client.close()
            except:
                pass
        self._connections.clear()


# Singleton instance
ssh_service = SSHService()
