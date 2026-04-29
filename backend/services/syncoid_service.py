"""
Syncoid Service - Gestione replica ZFS tra nodi
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, Tuple
import logging
import re

from services.ssh_service import ssh_service, SSHResult

logger = logging.getLogger(__name__)


class SyncoidService:
    """Servizio per replica ZFS con Syncoid"""
    
    def build_syncoid_command(
        self,
        source_host: Optional[str],
        source_dataset: str,
        dest_host: Optional[str],
        dest_dataset: str,
        source_user: str = "root",
        dest_user: str = "root",
        source_port: int = 22,
        dest_port: int = 22,
        source_key: str = "/root/.ssh/id_rsa",
        dest_key: str = "/root/.ssh/id_rsa",
        recursive: bool = False,
        compress: str = "lz4",
        mbuffer_size: str = "128M",
        no_sync_snap: bool = False,
        force_delete: bool = False,
        extra_args: str = ""
    ) -> str:
        """
        Costruisce il comando syncoid.
        Usa sintassi compatibile con tutte le versioni di syncoid.
        
        Sintassi syncoid:
        - syncoid source dest                      (locale -> locale)
        - syncoid source user@host:dest            (locale -> remoto, push)
        - syncoid user@host:source dest            (remoto -> locale, pull)
        - syncoid user@host:source user@host:dest  (remoto -> remoto)
        """
        
        cmd_parts = ["syncoid"]
        
        # Opzioni base
        if recursive:
            cmd_parts.append("--recursive")
        
        if compress and compress != "none":
            cmd_parts.append(f"--compress={compress}")
        
        if mbuffer_size:
            cmd_parts.append(f"--mbuffer-size={mbuffer_size}")
        
        if no_sync_snap:
            cmd_parts.append("--no-sync-snap")
        
        if force_delete:
            cmd_parts.append("--force-delete")
        
        # SSH options (compatibile con tutte le versioni)
        # NOTA: syncoid viene eseguito sul nodo Proxmox, quindi la chiave SSH
        # per la connessione interna tra nodi è sempre /root/.ssh/id_rsa
        # (indipendentemente dal key path usato per connettersi al nodo esecutore)
        PROXMOX_SSH_KEY = "/root/.ssh/id_rsa"
        
        if dest_host:
            # Push a destinazione remota - usa opzioni SSH per la destinazione
            cmd_parts.append(f"--sshkey={PROXMOX_SSH_KEY}")
            if dest_port != 22:
                cmd_parts.append(f"--sshport={dest_port}")
        elif source_host:
            # Pull da sorgente remota - usa opzioni SSH per la sorgente
            cmd_parts.append(f"--sshkey={PROXMOX_SSH_KEY}")
            if source_port != 22:
                cmd_parts.append(f"--sshport={source_port}")
        
        if extra_args:
            cmd_parts.append(extra_args)
        
        # Costruisci sorgente
        if source_host:
            source = f"{source_user}@{source_host}:{source_dataset}"
        else:
            source = source_dataset
        
        # Costruisci destinazione
        if dest_host:
            dest = f"{dest_user}@{dest_host}:{dest_dataset}"
        else:
            dest = dest_dataset
        
        cmd_parts.append(source)
        cmd_parts.append(dest)
        
        return " ".join(cmd_parts)
    
    async def run_sync(
        self,
        executor_host: str,  # Nodo da cui eseguire syncoid
        source_host: Optional[str],  # None se locale all'executor
        source_dataset: str,
        dest_host: Optional[str],  # None se locale all'executor
        dest_dataset: str,
        source_user: str = "root",
        dest_user: str = "root",
        source_port: int = 22,
        dest_port: int = 22,
        executor_port: int = 22,
        executor_user: str = "root",
        executor_key: str = "/root/.ssh/id_rsa",
        source_key: str = "/root/.ssh/id_rsa",
        dest_key: str = "/root/.ssh/id_rsa",
        recursive: bool = False,
        compress: str = "lz4",
        mbuffer_size: str = "128M",
        no_sync_snap: bool = False,
        force_delete: bool = False,
        extra_args: str = "",
        timeout: int = 3600
    ) -> Dict:
        """
        Esegue una sincronizzazione Syncoid
        
        Returns dict con:
            - success: bool
            - output: str
            - error: str
            - duration: int (secondi)
            - transferred: str (es: "1.5G")
        """
        
        start_time = datetime.utcnow()
        
        # Costruisci comando
        cmd = self.build_syncoid_command(
            source_host=source_host,
            source_dataset=source_dataset,
            dest_host=dest_host,
            dest_dataset=dest_dataset,
            source_user=source_user,
            dest_user=dest_user,
            source_port=source_port,
            dest_port=dest_port,
            source_key=source_key,
            dest_key=dest_key,
            recursive=recursive,
            compress=compress,
            mbuffer_size=mbuffer_size,
            no_sync_snap=no_sync_snap,
            force_delete=force_delete,
            extra_args=extra_args
        )
        
        # Pre-fetch host keys of any remote endpoints into the executor's
        # ~/.ssh/known_hosts, otherwise syncoid's inner ssh fails with
        # "Host key verification failed" on first contact.
        remote_endpoints = []
        for host, port in ((source_host, source_port), (dest_host, dest_port)):
            if host and host != executor_host:
                remote_endpoints.append((host, port))
        if remote_endpoints:
            await self._ensure_known_hosts(
                executor_host=executor_host,
                executor_port=executor_port,
                executor_user=executor_user,
                executor_key=executor_key,
                endpoints=remote_endpoints,
            )
            await self._ensure_executor_authorized(
                executor_host=executor_host,
                executor_port=executor_port,
                executor_user=executor_user,
                executor_key=executor_key,
                endpoints=remote_endpoints,
            )

        logger.info(f"Esecuzione syncoid: {cmd}")

        # Esegui comando
        result = await ssh_service.execute(
            hostname=executor_host,
            command=cmd,
            port=executor_port,
            username=executor_user,
            key_path=executor_key,
            timeout=timeout
        )
        
        end_time = datetime.utcnow()
        duration = int((end_time - start_time).total_seconds())
        
        # Parse output per trasferimento
        transferred = self._parse_transferred(result.stdout + result.stderr)
        
        return {
            "success": result.success,
            "output": result.stdout,
            "error": result.stderr,
            "duration": duration,
            "transferred": transferred,
            "command": cmd
        }
    
    async def _ensure_known_hosts(
        self,
        executor_host: str,
        executor_port: int,
        executor_user: str,
        executor_key: str,
        endpoints: list,  # list[tuple[host, port]]
    ) -> None:
        """
        Su `executor_host`, aggiunge le host key di `endpoints` a
        ~/.ssh/known_hosts (idempotente). Best-effort: log e prosegue.
        """
        # Build a single shell command that:
        #  - skips already-known hosts (ssh-keygen -F)
        #  - keyscan'a quelli mancanti e appende
        #  - dedup finale
        parts = ["mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/known_hosts"]
        for host, port in endpoints:
            # Quoting difensivo: gli host arrivano dal DB (hostname/IP), non da input utente diretto.
            host_q = host.replace('"', '').replace("'", "").replace(" ", "")
            port_i = int(port)
            parts.append(
                f'if ! ssh-keygen -F "[{host_q}]:{port_i}" >/dev/null 2>&1 && '
                f'! ssh-keygen -F "{host_q}" >/dev/null 2>&1; then '
                f'ssh-keyscan -H -p {port_i} -T 5 "{host_q}" >> ~/.ssh/known_hosts 2>/dev/null || true; '
                f'fi'
            )
        parts.append("sort -u ~/.ssh/known_hosts -o ~/.ssh/known_hosts || true")
        cmd = " && ".join(parts)

        try:
            result = await ssh_service.execute(
                hostname=executor_host,
                command=cmd,
                port=executor_port,
                username=executor_user,
                key_path=executor_key,
                timeout=30,
            )
            if not result.success:
                logger.warning(
                    f"ssh-keyscan pre-step ha restituito errore su {executor_host}: "
                    f"{result.stderr or result.stdout}"
                )
        except Exception as e:
            logger.warning(f"ssh-keyscan pre-step fallito su {executor_host}: {e}")

    async def _ensure_executor_authorized(
        self,
        executor_host: str,
        executor_port: int,
        executor_user: str,
        executor_key: str,
        endpoints: list,  # list[tuple[host, port]]
    ) -> None:
        """
        Garantisce che la chiave pubblica dell'executor sia presente in
        ~/.ssh/authorized_keys di ogni endpoint remoto. Senza questo,
        syncoid (eseguito sull'executor) fallisce con
        "Permission denied (publickey,password)" alla connessione interna.

        Funziona perché il server dapx ha SSH verso *tutti* i nodi (chiave
        propria distribuita all'add-node), quindi può leggere la pub key
        dell'executor e appenderla sul remote senza richiedere password.
        Best-effort: log e prosegue.
        """
        # 1) Leggi la pub key dell'executor
        try:
            r = await ssh_service.execute(
                hostname=executor_host,
                command="cat ~/.ssh/id_rsa.pub 2>/dev/null || cat ~/.ssh/id_ed25519.pub 2>/dev/null",
                port=executor_port,
                username=executor_user,
                key_path=executor_key,
                timeout=10,
            )
            pubkey = (r.stdout or "").strip()
            if not r.success or not pubkey:
                logger.warning(
                    f"Impossibile leggere la chiave pubblica su {executor_host}: "
                    f"{r.stderr or 'output vuoto'}"
                )
                return
        except Exception as e:
            logger.warning(f"Lettura pub key fallita su {executor_host}: {e}")
            return

        # Sanitize: prendi solo la prima riga, niente caratteri di controllo
        pubkey_line = pubkey.splitlines()[0].strip()
        if "'" in pubkey_line:
            logger.warning("Pub key contiene apostrofi, salto distribuzione")
            return

        # 2) Per ogni endpoint, appendi se non già presente
        for host, port in endpoints:
            cmd = (
                "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && "
                f"grep -qxF '{pubkey_line}' ~/.ssh/authorized_keys || "
                f"echo '{pubkey_line}' >> ~/.ssh/authorized_keys"
            )
            try:
                r = await ssh_service.execute(
                    hostname=host,
                    command=cmd,
                    port=int(port),
                    username=executor_user,
                    key_path=executor_key,
                    timeout=15,
                )
                if not r.success:
                    logger.warning(
                        f"Append pub key su {host} fallito: "
                        f"{r.stderr or r.stdout}"
                    )
            except Exception as e:
                logger.warning(f"Append pub key su {host} ha sollevato: {e}")

    def _parse_transferred(self, output: str) -> Optional[str]:
        """Estrae la quantità di dati trasferiti dall'output di syncoid"""
        # Pattern comuni nell'output di syncoid
        patterns = [
            r"(\d+(?:\.\d+)?[KMGT]i?B?)\s+transferred",
            r"sent\s+(\d+(?:\.\d+)?[KMGT]i?B?)",
            r"(\d+(?:\.\d+)?[KMGT]i?B?)\s+total",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    async def verify_datasets_exist(
        self,
        hostname: str,
        datasets: list,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, bool]:
        """Verifica che i dataset esistano su un nodo"""
        results = {}
        
        for ds in datasets:
            result = await ssh_service.execute(
                hostname=hostname,
                command=f"zfs list -H -o name {ds} 2>/dev/null",
                port=port,
                username=username,
                key_path=key_path
            )
            results[ds] = result.success and ds in result.stdout
        
        return results
    
    async def create_dataset(
        self,
        hostname: str,
        dataset: str,
        parent_must_exist: bool = True,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> SSHResult:
        """Crea un dataset ZFS"""
        flags = "-p" if not parent_must_exist else ""
        cmd = f"zfs create {flags} {dataset}"
        
        return await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
    
    async def get_last_common_snapshot(
        self,
        source_host: str,
        source_dataset: str,
        dest_host: str,
        dest_dataset: str,
        source_port: int = 22,
        dest_port: int = 22,
        source_user: str = "root",
        dest_user: str = "root",
        source_key: str = "/root/.ssh/id_rsa",
        dest_key: str = "/root/.ssh/id_rsa"
    ) -> Optional[str]:
        """Trova l'ultimo snapshot comune tra sorgente e destinazione"""
        
        # Ottieni snapshot sorgente
        source_result = await ssh_service.execute(
            hostname=source_host,
            command=f"zfs list -H -t snapshot -o name -s creation {source_dataset}",
            port=source_port,
            username=source_user,
            key_path=source_key
        )
        
        if not source_result.success:
            return None
        
        source_snaps = set()
        for line in source_result.stdout.strip().split('\n'):
            if '@' in line:
                snap_name = line.split('@')[1]
                source_snaps.add(snap_name)
        
        # Ottieni snapshot destinazione
        dest_result = await ssh_service.execute(
            hostname=dest_host,
            command=f"zfs list -H -t snapshot -o name -s creation {dest_dataset}",
            port=dest_port,
            username=dest_user,
            key_path=dest_key
        )
        
        if not dest_result.success:
            return None
        
        dest_snaps = []
        for line in dest_result.stdout.strip().split('\n'):
            if '@' in line:
                snap_name = line.split('@')[1]
                if snap_name in source_snaps:
                    dest_snaps.append(snap_name)
        
        # Ritorna l'ultimo comune (il più recente per creation time)
        return dest_snaps[-1] if dest_snaps else None


# Singleton
syncoid_service = SyncoidService()
