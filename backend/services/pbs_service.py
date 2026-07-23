"""
PBS Service - Gestione Proxmox Backup Server
Permette backup e restore di VM attraverso PBS per replica di filesystem non supportati
"""

import asyncio
from typing import Optional, Dict, List, Tuple, Any
import logging
import json
import re
import shlex
import time
from datetime import datetime, timedelta
import aiohttp
import ssl
import urllib.parse

from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)

# Cache inventario PBS (evita chiamate ripetute a PBS/pvesh per ogni expand VM)
_INVENTORY_CACHE: Dict[str, Tuple[float, List[Dict]]] = {}
INVENTORY_CACHE_TTL_SEC = 300


def inventory_cache_key(
    pbs_node_id: int,
    datastore: str,
    pve_node_id: Optional[int] = None,
    pbs_storage: Optional[str] = None,
) -> str:
    return f"{pbs_node_id}:{datastore}:{pve_node_id or ''}:{pbs_storage or ''}"


def summarize_inventory_entries(entries: List[Dict]) -> List[Dict]:
    """Raggruppa snapshot per VMID → riepilogo (senza catena date)."""
    groups: Dict[int, Dict] = {}
    for entry in entries:
        vmid = entry.get("vmid")
        if vmid is None:
            continue
        vmid = int(vmid)
        group = groups.get(vmid)
        if not group:
            group = {
                "vmid": vmid,
                "vm_name": entry.get("vm_name") or f"VM #{vmid}",
                "vm_type": entry.get("vm_type") or "qemu",
                "backup_count": 0,
                "latest_backup_time": 0,
                "latest_size": 0,
            }
            groups[vmid] = group
        name = entry.get("vm_name")
        if name and (group["vm_name"].startswith("VM #") or group["vm_name"].startswith("CT #")):
            group["vm_name"] = name
        group["backup_count"] += 1
        btime = int(entry.get("backup_time") or 0)
        if btime >= group["latest_backup_time"]:
            group["latest_backup_time"] = btime
            group["latest_size"] = entry.get("size") or 0

    return sorted(
        groups.values(),
        key=lambda g: g["latest_backup_time"],
        reverse=True,
    )


def filter_inventory_by_vmid(entries: List[Dict], vm_id: int) -> List[Dict]:
    return [e for e in entries if e.get("vmid") == vm_id]


# Pattern di validazione per evitare command injection nei comandi
# vzdump/qmrestore/pct restore costruiti via SSH. Tutti gli identifier
# che finiscono in shell devono passare uno di questi check.
_PBS_STORAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-.]*$")
_PBS_DATASTORE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-.]*$")
_PBS_BACKUP_ID_RE = re.compile(r"^(?:vm|ct)/\d+/[0-9TZ:.\-]+$")
_PBS_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*@[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
_PBS_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")
_PBS_MODE_ALLOWED = {"snapshot", "stop", "suspend"}
_PBS_COMPRESS_ALLOWED = {"none", "lzo", "gzip", "zstd"}
_PBS_VMTYPE_ALLOWED = {"qemu", "lxc"}


def _check(value: Optional[str], regex: re.Pattern, label: str) -> str:
    if value is None or not regex.match(value):
        raise ValueError(f"PBS {label} non valido: {value!r}")
    return value


def _check_in(value: Optional[str], allowed: set, label: str) -> str:
    if value is None or value not in allowed:
        raise ValueError(f"PBS {label} non valido: {value!r}")
    return value


def _check_int(value, label: str, lo: int = 100, hi: int = 999_999_999) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"PBS {label} non valido: {value!r}")
    if not (lo <= n <= hi):
        raise ValueError(f"PBS {label} fuori range: {n}")
    return n


def pbs_snapshot_restore_path(backup_type: str, backup_id, backup_time: int) -> str:
    """Da campi API PBS → path restore `vm/100/2024-01-01T00:00:00Z`."""
    prefix = "ct" if backup_type in ("ct", "lxc") else "vm"
    bid_raw = str(backup_id or "")
    if "/" in bid_raw:
        # già vm/100/2024-... o ct/101/...
        if re.fullmatch(r"(?:vm|ct)/\d+/[0-9TZ:.\-]+", bid_raw):
            return bid_raw
        bid_raw = bid_raw.rstrip("/").split("/")[-2 if bid_raw.endswith("/") else -1]
    ts = int(backup_time or 0)
    iso = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{prefix}/{bid_raw}/{iso}"


def normalize_pbs_api_snapshot(snap: Dict, pbs_storage: Optional[str] = None) -> Dict:
    """Normalizza uno snapshot PBS API in entry inventario con path restore univoco."""
    btype = snap.get("backup-type") or snap.get("subtype") or "vm"
    bid = snap.get("backup-id")
    btime = snap.get("backup-time") or snap.get("backup_time") or 0
    restore_path = pbs_snapshot_restore_path(btype, bid, btime)
    vmid = None
    if bid is not None and str(bid).isdigit():
        vmid = int(bid)
    else:
        m = re.search(r"(?:vm|ct)/(\d+)/", restore_path)
        if m:
            vmid = int(m.group(1))
    vm_type = "lxc" if btype in ("ct", "lxc") or "/ct/" in restore_path else "qemu"
    volid = snap.get("volid")
    if not volid and pbs_storage:
        volid = f"{pbs_storage}:backup/{restore_path}"
    name = snap.get("comment") or snap.get("notes") or snap.get("vm_name")
    return {
        "backup-id": restore_path,
        "backup_id": restore_path,
        "restore_path": restore_path,
        "volid": volid or restore_path,
        "vmid": vmid if vmid is not None else snap.get("vmid"),
        "vm_name": name or (f"{'CT' if vm_type == 'lxc' else 'VM'} #{vmid}" if vmid else ""),
        "vm_type": vm_type,
        "backup_time": int(btime) * 1000 if btime else 0,
        "size": snap.get("size", 0),
    }


def normalize_pvesh_backup_entry(entry: Dict, pbs_storage: Optional[str] = None) -> Dict:
    """Normalizza riga pvesh storage content in entry inventario."""
    volid = entry.get("volid", "") or ""
    restore_path = volid
    if ":backup/" in volid:
        restore_path = volid.split(":backup/", 1)[1]
    elif volid.startswith("backup/"):
        restore_path = volid[len("backup/"):]
    vm_type = "lxc" if "/ct/" in restore_path or entry.get("subtype") == "lxc" else "qemu"
    vmid = entry.get("vmid")
    if vmid is None:
        m = re.search(r"(?:vm|ct)/(\d+)/", restore_path)
        if m:
            vmid = int(m.group(1))
    ctime = entry.get("ctime", 0) or 0
    return {
        "backup-id": restore_path,
        "backup_id": restore_path,
        "restore_path": restore_path,
        "volid": volid or (f"{pbs_storage}:backup/{restore_path}" if pbs_storage else restore_path),
        "vmid": vmid,
        "vm_name": entry.get("notes") or entry.get("comment") or (f"{'CT' if vm_type == 'lxc' else 'VM'} #{vmid}" if vmid else ""),
        "vm_type": vm_type,
        "backup_time": int(ctime) * 1000 if ctime else 0,
        "size": entry.get("size", 0),
    }


class PBSService:
    """Servizio per integrazione con Proxmox Backup Server"""
    
    def __init__(self):
        self._ticket_cache = {}

    def _get_ssl_context(
        self,
        verify_ssl: bool = False,
        fingerprint: Optional[str] = None,
    ) -> ssl.SSLContext:
        """Contesto SSL per chiamate PBS.

        - verify_ssl=True senza fingerprint -> CA bundle standard.
        - fingerprint set -> CERT_NONE ma il chiamante deve verificare
          manualmente lo SHA-256 del cert con `_verify_peer_fingerprint`.
        - altrimenti -> CERT_NONE (legacy, sconsigliato).
        """
        if verify_ssl and not fingerprint:
            return ssl.create_default_context()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    @staticmethod
    def _normalize_fingerprint(fp: str) -> str:
        return (fp or "").replace(":", "").replace(" ", "").upper()

    async def _verify_peer_fingerprint(
        self,
        hostname: str,
        port: int,
        expected_fp: str,
    ) -> bool:
        """SHA-256 pinning del cert PBS. True se combacia."""
        if not expected_fp:
            return False
        expected = self._normalize_fingerprint(expected_fp)
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            loop = asyncio.get_event_loop()

            def _grab_cert():
                import socket
                with socket.create_connection((hostname, int(port)), timeout=5) as raw:
                    with ctx.wrap_socket(raw, server_hostname=hostname) as sock:
                        return sock.getpeercert(binary_form=True)

            der = await loop.run_in_executor(None, _grab_cert)
            import hashlib
            actual = hashlib.sha256(der).hexdigest().upper()
            ok = actual == expected
            if not ok:
                logger.warning(
                    f"PBS fingerprint mismatch su {hostname}:{port} — "
                    f"atteso={expected[:16]}…, attuale={actual[:16]}…"
                )
            return ok
        except Exception as e:
            logger.warning(f"Verifica fingerprint PBS {hostname} fallita: {e}")
            return False

    async def _get_ticket(
        self,
        hostname: str,
        port: int,
        username: str,
        password: str,
        fingerprint: Optional[str] = None,
    ) -> Optional[Dict]:
        """Ottiene ticket di autenticazione da PBS.

        Se `fingerprint` e' impostato, viene verificato lo SHA-256 del
        certificato peer prima di trasmettere le credenziali. Senza
        fingerprint la chiamata resta funzionante (legacy) ma con un
        warning di sicurezza.
        """
        cache_key = f"{hostname}:{username}"
        if cache_key in self._ticket_cache:
            ticket_data = self._ticket_cache[cache_key]
            if datetime.now() < ticket_data['expires']:
                return ticket_data

        if fingerprint:
            ok = await self._verify_peer_fingerprint(hostname, port, fingerprint)
            if not ok:
                logger.error(
                    f"PBS {hostname}:{port}: fingerprint TLS non corrisponde, "
                    "rifiuto di trasmettere le credenziali."
                )
                return None
        else:
            logger.warning(
                f"PBS {hostname}:{port}: nessun fingerprint configurato, "
                "TLS non verificato (configura node.pbs_fingerprint)."
            )

        api_url = f"https://{hostname}:{port}/api2/json/access/ticket"
        ssl_ctx = self._get_ssl_context(False, fingerprint)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, data={"username": username, "password": password}, ssl=ssl_ctx) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get('data', {})
                        ticket = result.get('ticket')
                        csrf = result.get('CSRFPreventionToken')
                        if ticket:
                            self._ticket_cache[cache_key] = {
                                'ticket': ticket,
                                'csrf': csrf,
                                'expires': datetime.now() + timedelta(hours=1)
                            }
                            return self._ticket_cache[cache_key]
                    else:
                        logger.warning(f"PBS Auth failed: {resp.status} - {await resp.text()}")
        except Exception as e:
            logger.error(f"Error getting PBS ticket: {e}")
        return None

    async def list_backups_api(
        self,
        pbs_hostname: str,
        datastore: str,
        pbs_user: str,
        pbs_password: str,
        vm_id: int = None,
        port: int = 8007,
        pbs_fingerprint: Optional[str] = None,
    ) -> List[Dict]:
        """Lista i backup usando l'API HTTP di PBS (porta 8007).

        Se `pbs_fingerprint` e' impostato (dal record Node), viene
        eseguito il pinning TLS prima della call.
        """
        ticket_data = await self._get_ticket(
            pbs_hostname, port, pbs_user, pbs_password, pbs_fingerprint
        )
        if not ticket_data:
            raise Exception("Authentication failed")

        api_url = f"https://{pbs_hostname}:{port}/api2/json/admin/datastore/{datastore}/snapshots"
        ssl_ctx = self._get_ssl_context(False)
        
        # PBSAuthCookie must be passed. Ensure no URL encoding issues.
        # usually requests/aiohttp handles cookies transparently.
        # But if the ticket contains special chars it might be an issue.
        # Let's try explicit header instead.
        # headers = {"Cookie": f"PBSAuthCookie={ticket_data['ticket']}"}
        
        
        cookies = {"PBSAuthCookie": urllib.parse.quote_plus(ticket_data['ticket'])}
        
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.get(api_url, ssl=ssl_ctx) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        snapshots = data.get('data', [])
                        
                        results = []
                        for snap in snapshots:
                            if vm_id is not None:
                                snap_vmid = snap.get("backup-id")
                                if str(snap_vmid) != str(vm_id):
                                    continue
                            results.append(normalize_pbs_api_snapshot(snap))
                        return results
                    else:
                        logger.error(f"PBS List snapshots failed: {resp.status} - {await resp.text()}")
                        # If 401, clear cache and retry once?
                        if resp.status == 401:
                             self._ticket_cache.pop(f"{pbs_hostname}:{pbs_user}", None)
                        return []
        except Exception as e:
            logger.error(f"Error listing PBS backups via API: {e}")
            return []
    
    async def list_vm_backups(
        self,
        pbs_node: Any, # Expects a database.Node object
        vm_id: int,
        vm_type: str = "qemu",
        datastore: str = None
    ) -> List[Dict]:
        """
        Metodo di compatibilità per backup_jobs.py
        Usa API se possibile, altrimenti fallback SSH
        """
        if not datastore:
            datastore = pbs_node.pbs_datastore
            
        if not datastore:
            raise ValueError("Datastore non specificato e non presente nel nodo PBS")

        # Try API first
        if pbs_node.pbs_password:
            try:
                return await self.list_backups_api(
                    pbs_hostname=pbs_node.hostname,
                    datastore=datastore,
                    pbs_user=pbs_node.pbs_username or "root@pam",
                    pbs_password=pbs_node.pbs_password,
                    vm_id=vm_id,
                    pbs_fingerprint=pbs_node.pbs_fingerprint,
                )
            except Exception as e:
                logger.warning(f"API list backups failed, trying SSH fallback: {e}")

        raw = await self.list_backups(
            pbs_hostname=pbs_node.hostname,
            datastore=datastore,
            pbs_user=pbs_node.pbs_username or "root@pam",
            pbs_password=pbs_node.pbs_password,
            pbs_fingerprint=pbs_node.pbs_fingerprint,
            vm_id=vm_id,
        )
        return [normalize_pbs_api_snapshot(b) for b in raw]

    async def list_inventory_backups(
        self,
        pbs_node: Any,
        datastore: str,
        vm_id: Optional[int] = None,
        pve_node: Any = None,
        pbs_storage: Optional[str] = None,
    ) -> List[Dict]:
        """Elenco completo versioni backup PBS (API preferita, supplemento pvesh)."""
        results: List[Dict] = []
        seen: set = set()

        def _add(entry: Dict) -> None:
            path = entry.get("restore_path") or entry.get("backup_id") or entry.get("backup-id")
            if not path or path in seen:
                return
            if vm_id is not None and entry.get("vmid") != vm_id:
                return
            seen.add(path)
            results.append(entry)

        if pbs_node.pbs_password:
            try:
                api_items = await self.list_backups_api(
                    pbs_hostname=pbs_node.hostname,
                    datastore=datastore,
                    pbs_user=pbs_node.pbs_username or "root@pam",
                    pbs_password=pbs_node.pbs_password,
                    vm_id=vm_id,
                    pbs_fingerprint=pbs_node.pbs_fingerprint,
                )
                for item in api_items:
                    _add(item)
            except Exception as e:
                logger.warning(f"PBS API inventory fallita: {e}")

        if pve_node and pbs_storage:
            from services.ssh_service import ssh_service

            cmd = (
                f"pvesh get /nodes/{pve_node.name}/storage/{pbs_storage}/content "
                f"--content backup --output-format json 2>/dev/null"
            )
            if vm_id is not None:
                cmd = (
                    f"pvesh get /nodes/{pve_node.name}/storage/{pbs_storage}/content "
                    f"--content backup --vmid {int(vm_id)} --output-format json 2>/dev/null"
                )
            result = await ssh_service.execute(
                hostname=pve_node.hostname,
                command=cmd,
                port=pve_node.ssh_port,
                username=pve_node.ssh_user,
                key_path=pve_node.ssh_key_path,
            )
            if result.success and result.stdout.strip():
                try:
                    for row in json.loads(result.stdout):
                        _add(normalize_pvesh_backup_entry(row, pbs_storage))
                except json.JSONDecodeError as e:
                    logger.warning(f"pvesh inventory parse error: {e}")

        results.sort(key=lambda x: x.get("backup_time", 0), reverse=True)
        return results

    async def get_cached_inventory_entries(
        self,
        pbs_node: Any,
        datastore: str,
        vm_id: Optional[int] = None,
        pve_node: Any = None,
        pbs_storage: Optional[str] = None,
        force_refresh: bool = False,
    ) -> List[Dict]:
        """Inventario completo con cache TTL (condivisa tra summary e dettaglio VM)."""
        key = inventory_cache_key(
            int(pbs_node.id),
            datastore,
            getattr(pve_node, "id", None) if pve_node else None,
            pbs_storage,
        )
        now = time.time()
        if not force_refresh and key in _INVENTORY_CACHE:
            ts, cached = _INVENTORY_CACHE[key]
            if now - ts < INVENTORY_CACHE_TTL_SEC:
                entries = cached
                if vm_id is not None:
                    return filter_inventory_by_vmid(entries, vm_id)
                return entries

        entries = await self.list_inventory_backups(
            pbs_node=pbs_node,
            datastore=datastore,
            vm_id=vm_id,
            pve_node=pve_node,
            pbs_storage=pbs_storage,
        )
        if vm_id is None:
            _INVENTORY_CACHE[key] = (now, entries)
        return entries

    async def list_inventory_vm_summaries(
        self,
        pbs_node: Any,
        datastore: str,
        pve_node: Any = None,
        pbs_storage: Optional[str] = None,
        force_refresh: bool = False,
    ) -> List[Dict]:
        entries = await self.get_cached_inventory_entries(
            pbs_node=pbs_node,
            datastore=datastore,
            pve_node=pve_node,
            pbs_storage=pbs_storage,
            force_refresh=force_refresh,
        )
        return summarize_inventory_entries(entries)

    async def list_inventory_vm_versions(
        self,
        pbs_node: Any,
        datastore: str,
        vm_id: int,
        pve_node: Any = None,
        pbs_storage: Optional[str] = None,
        force_refresh: bool = False,
    ) -> List[Dict]:
        entries = await self.get_cached_inventory_entries(
            pbs_node=pbs_node,
            datastore=datastore,
            vm_id=vm_id,
            pve_node=pve_node,
            pbs_storage=pbs_storage,
            force_refresh=force_refresh,
        )
        if not entries:
            key = inventory_cache_key(
                int(pbs_node.id),
                datastore,
                getattr(pve_node, "id", None) if pve_node else None,
                pbs_storage,
            )
            now = time.time()
            if key in _INVENTORY_CACHE:
                _, cached = _INVENTORY_CACHE[key]
                entries = filter_inventory_by_vmid(cached, vm_id)
            else:
                entries = await self.list_inventory_backups(
                    pbs_node=pbs_node,
                    datastore=datastore,
                    vm_id=vm_id,
                    pve_node=pve_node,
                    pbs_storage=pbs_storage,
                )
        return sorted(entries, key=lambda x: x.get("backup_time", 0), reverse=True)

    async def check_pbs_available(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifica se proxmox-backup-client è installato sul nodo
        Ritorna (disponibile, versione)
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="proxmox-backup-client version 2>/dev/null || echo 'NOT_INSTALLED'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and "NOT_INSTALLED" not in result.stdout:
            # Parse version from output like "proxmox-backup-client 3.1.2-1"
            version_match = re.search(r'(\d+\.\d+\.\d+)', result.stdout)
            version = version_match.group(1) if version_match else "unknown"
            return True, version
        
        return False, None
    
    async def check_pbs_server(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifica se il nodo è un PBS server (proxmox-backup-server installato)
        Ritorna (is_pbs_server, versione)
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="proxmox-backup-manager version 2>/dev/null || echo 'NOT_PBS'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and "NOT_PBS" not in result.stdout:
            version_match = re.search(r'(\d+\.\d+\.\d+)', result.stdout)
            version = version_match.group(1) if version_match else "unknown"
            return True, version
        
        return False, None
    
    async def get_fingerprint(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Optional[str]:
        """
        Ottiene il fingerprint SSL del server PBS
        """
        # Prova prima comando senza JSON (universale)
        result = await ssh_service.execute(
            hostname=hostname,
            command="proxmox-backup-manager cert info",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            # Output tipico:
            # Fingerprint (sha256): xx:xx:xx:xx...
            match = re.search(r'Fingerprint \(sha256\):\s*([0-9a-fA-F:]+)', result.stdout)
            if match:
                return match.group(1).strip()
            
            # Fallback JSON (per versioni future)
            # ...
        
        return None

    async def list_datastores(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """
        Lista i datastore disponibili su un PBS server
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="proxmox-backup-manager datastore list --output-format json 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse datastore list: {result.stdout}")
        
        return []
    
    async def list_datastore_names(self, node: Any) -> List[str]:
        """Elenco nomi datastore PBS (SSH preferito, fallback API)."""
        names: List[str] = []

        if node.hostname and node.ssh_user:
            stores = await self.list_datastores(
                hostname=node.hostname,
                port=getattr(node, "ssh_port", 22) or 22,
                username=node.ssh_user,
                key_path=getattr(node, "ssh_key_path", None) or "/root/.ssh/id_rsa",
            )
            for item in stores:
                for key in ("store", "name", "datastore"):
                    val = item.get(key)
                    if val:
                        names.append(str(val))
                        break

        if not names and getattr(node, "pbs_password", None):
            ticket_data = await self._get_ticket(
                node.hostname,
                8007,
                node.pbs_username or "root@pam",
                node.pbs_password,
                getattr(node, "pbs_fingerprint", None),
            )
            if ticket_data:
                api_url = f"https://{node.hostname}:8007/api2/json/admin/datastore"
                ssl_ctx = self._get_ssl_context(False)
                cookies = {"PBSAuthCookie": urllib.parse.quote_plus(ticket_data["ticket"])}
                try:
                    async with aiohttp.ClientSession(cookies=cookies) as session:
                        async with session.get(api_url, ssl=ssl_ctx) as resp:
                            if resp.status == 200:
                                payload = await resp.json()
                                for item in payload.get("data", []):
                                    val = item.get("store") or item.get("name")
                                    if val:
                                        names.append(str(val))
                except Exception as e:
                    logger.warning(f"PBS API datastore list fallita: {e}")

        return sorted(set(names))

    async def list_backups(
        self,
        pbs_hostname: str,
        datastore: str,
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        vm_id: Optional[int] = None,
        from_node_hostname: Optional[str] = None,
        from_node_port: int = 22,
        from_node_user: str = "root",
        from_node_key: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """
        Lista i backup disponibili su un PBS datastore.
        Esegue il comando da from_node se specificato, altrimenti direttamente sul PBS.
        """
        
        # Build PBS repository string
        pbs_repo = f"{pbs_user}@{pbs_hostname}:{datastore}"
        
        # Build command
        cmd_parts = ["proxmox-backup-client", "snapshot", "list", "--repository", pbs_repo]
        
        if pbs_fingerprint:
            cmd_parts.extend(["--fingerprint", pbs_fingerprint])
        
        cmd_parts.append("--output-format json")
        
        # Add password via environment if provided
        env_prefix = ""
        if pbs_password:
            env_prefix = f"PBS_PASSWORD={shlex.quote(pbs_password)} "

        if pbs_fingerprint:
            env_prefix += f"PBS_FINGERPRINT={shlex.quote(pbs_fingerprint)} "
        
        cmd = env_prefix + " ".join(cmd_parts) + " 2>/dev/null"
        
        # Execute from node or directly
        exec_host = from_node_hostname or pbs_hostname
        exec_port = from_node_port if from_node_hostname else (from_node_port if from_node_port != 22 else 22) # Use provided port or default to 22 if not specified. Actually, rely on argument passed.
        # Improvement: If connecting directly to PBS (from_node_hostname is None), we want to use the PBS node's SSH details.
        # But the arguments specifically say "from_node_...".
        # Let's just use the passed arguments. The caller (vms.py) should pass the correct values.
        exec_port = from_node_port
        exec_user = from_node_user
        exec_key = from_node_key
        
        result = await ssh_service.execute(
            hostname=exec_host,
            command=cmd,
            port=exec_port,
            username=exec_user,
            key_path=exec_key
        )
        
        backups = []
        if result.success and result.stdout.strip():
            try:
                all_backups = json.loads(result.stdout)
                # Filter by VM ID if specified
                if vm_id is not None:
                    for backup in all_backups:
                        bid = str(backup.get("backup-id", ""))
                        if bid == str(vm_id) or f"/{vm_id}/" in bid:
                            backups.append(normalize_pbs_api_snapshot(backup))
                else:
                    backups = [normalize_pbs_api_snapshot(b) for b in all_backups]
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse backup list: {result.stdout}")
        
        return backups
    
    async def get_latest_backup(
        self,
        pbs_hostname: str,
        datastore: str,
        vm_id: int,
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        from_node_hostname: Optional[str] = None,
        from_node_port: int = 22,
        from_node_user: str = "root",
        from_node_key: str = "/root/.ssh/id_rsa"
    ) -> Optional[Dict]:
        """
        Ottiene l'ultimo backup disponibile per una VM
        """
        backups = await self.list_backups(
            pbs_hostname=pbs_hostname,
            datastore=datastore,
            pbs_user=pbs_user,
            pbs_password=pbs_password,
            pbs_fingerprint=pbs_fingerprint,
            vm_id=vm_id,
            from_node_hostname=from_node_hostname,
            from_node_port=from_node_port,
            from_node_user=from_node_user,
            from_node_key=from_node_key
        )
        
        if not backups:
            return None
        
        # Sort by backup time and return latest
        sorted_backups = sorted(backups, key=lambda x: x.get("backup-time", ""), reverse=True)
        return sorted_backups[0] if sorted_backups else None
    
    async def _ensure_pbs_storage(
        self,
        node_hostname: str,
        storage_name: str,
        pbs_hostname: str,
        datastore: str,
        pbs_user: str,
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        node_port: int = 22,
        node_user: str = "root",
        node_key: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Assicura che lo storage PBS sia configurato sul nodo PVE.
        Prima cerca storage esistenti che puntano allo stesso server/datastore.
        Crea lo storage solo se non ne esiste già uno compatibile.
        
        Returns:
            (success, storage_name_used)
        """
        # 1. Check if the exact storage name already exists
        check_cmd = f"pvesm status 2>/dev/null | grep -q '^{storage_name} '"
        check_result = await ssh_service.execute(
            hostname=node_hostname,
            command=check_cmd,
            port=node_port,
            username=node_user,
            key_path=node_key
        )
        
        if check_result.exit_code == 0:
            logger.info(f"Storage {storage_name} already exists on {node_hostname}")
            return True, storage_name
        
        # 2. Search for ANY existing PBS storage pointing to same server and datastore
        find_cmd = f"grep -l 'server {pbs_hostname}' /etc/pve/storage.cfg 2>/dev/null && grep -l 'datastore {datastore}' /etc/pve/storage.cfg 2>/dev/null | head -1"
        # Better: parse storage.cfg directly
        parse_cmd = f"""python3 -c "
import re
with open('/etc/pve/storage.cfg') as f:
    content = f.read()
# Find all PBS storages
for match in re.finditer(r'pbs:\\s+(\\S+)\\n((?:^\\s+.*\\n)*)', content, re.MULTILINE):
    name = match.group(1)
    config = match.group(2)
    server = re.search(r'server\\s+(\\S+)', config)
    ds = re.search(r'datastore\\s+(\\S+)', config)
    if server and ds:
        if '{pbs_hostname}' in server.group(1) and '{datastore}' == ds.group(1):
            print(name)
            break
" 2>/dev/null"""
        
        find_result = await ssh_service.execute(
            hostname=node_hostname,
            command=parse_cmd,
            port=node_port,
            username=node_user,
            key_path=node_key
        )
        
        if find_result.exit_code == 0 and find_result.stdout and find_result.stdout.strip():
            existing_storage = find_result.stdout.strip()
            logger.info(f"Found existing PBS storage '{existing_storage}' pointing to {pbs_hostname}/{datastore}")
            return True, existing_storage
        
        # Crea lo storage PBS
        logger.info(f"Creating PBS storage {storage_name} on {node_hostname}")
        
        # Build add storage command
        add_cmd_parts = [
            "pvesm", "add", "pbs", storage_name,
            "--server", pbs_hostname,
            "--datastore", datastore,
            "--username", pbs_user,
            "--content", "backup"
        ]
        
        if pbs_fingerprint:
            # shlex.quote per gestire due punti/metacaratteri senza injection
            add_cmd_parts.extend(["--fingerprint", shlex.quote(pbs_fingerprint)])

        if pbs_password:
            add_cmd_parts.extend(["--password", shlex.quote(pbs_password)])
        
        add_cmd = " ".join(add_cmd_parts)
        
        # Log the exact command being executed (without password for security)
        safe_cmd = add_cmd.replace(pbs_password, "***") if pbs_password else add_cmd
        logger.info(f"PBS storage add command: {safe_cmd}")
        
        # Inject PBS_FINGERPRINT env var if present to ensure underlying client verification passes
        if pbs_fingerprint:
            add_cmd = f'PBS_FINGERPRINT="{pbs_fingerprint}" {add_cmd}'
        
        # Add 2>&1 to capture all output
        add_cmd += " 2>&1"
            
        add_result = await ssh_service.execute(
            hostname=node_hostname,
            command=add_cmd,
            port=node_port,
            username=node_user,
            key_path=node_key,
            timeout=60
        )
        
        # Log full result for debugging
        logger.info(f"PBS storage add result: exit_code={add_result.exit_code}, stdout={add_result.stdout}, stderr={add_result.stderr}")
        
        if add_result.success or add_result.exit_code == 0:
            logger.info(f"Storage {storage_name} created successfully on {node_hostname}")
            return True, f"Storage {storage_name} creato con successo"
        else:
            error_msg = add_result.stdout or add_result.stderr or "Errore sconosciuto"
            logger.error(f"Failed to create storage {storage_name}: {error_msg}")
            return False, f"Errore creazione storage: {error_msg}"
    
    async def run_backup(
        self,
        source_node_hostname: str,
        vm_id: int,
        pbs_hostname: str,
        datastore: str,
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        pbs_storage_id: Optional[str] = None,  # Nome storage PBS già configurato sul nodo
        vm_type: str = "qemu",
        mode: str = "snapshot",  # snapshot, stop, suspend
        compress: str = "zstd",  # none, lzo, gzip, zstd
        source_node_port: int = 22,
        source_node_user: str = "root",
        source_node_key: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """
        Esegue un backup di una VM verso PBS.
        
        Args:
            source_node_hostname: Hostname del nodo Proxmox VE sorgente
            vm_id: VMID della VM da backuppare
            pbs_hostname: Hostname del PBS server
            datastore: Nome del datastore PBS
            pbs_user: Utente PBS (es: root@pam)
            pbs_password: Password PBS
            pbs_fingerprint: Fingerprint SSL del PBS
            pbs_storage_id: Nome dello storage PBS già configurato sul nodo (se None, ne crea uno nuovo)
            vm_type: qemu o lxc
            mode: Modalità backup (snapshot, stop, suspend)
            compress: Algoritmo compressione
        
        Returns:
            Dict con success, backup_id, message, output
        """
        start_time = datetime.utcnow()

        # Validazione difensiva di TUTTI gli input che finiranno nel
        # comando vzdump/pvesm via SSH come root. Senza questi check un
        # valore controllato (anche da DB compromesso) e' RCE.
        try:
            vm_id_int = _check_int(vm_id, "vm_id")
            _check(source_node_hostname, _PBS_HOST_RE, "source_node_hostname")
            _check(pbs_hostname, _PBS_HOST_RE, "pbs_hostname")
            _check(datastore, _PBS_DATASTORE_RE, "datastore")
            _check(pbs_user, _PBS_USER_RE, "pbs_user")
            _check_in(vm_type, _PBS_VMTYPE_ALLOWED, "vm_type")
            _check_in(mode, _PBS_MODE_ALLOWED, "mode")
            _check_in(compress, _PBS_COMPRESS_ALLOWED, "compress")
            if pbs_storage_id:
                _check(pbs_storage_id, _PBS_STORAGE_RE, "pbs_storage_id")
            if pbs_fingerprint:
                # accettiamo formati con `:` o senza
                fp = self._normalize_fingerprint(pbs_fingerprint)
                if not re.fullmatch(r"[0-9A-F]{64}", fp):
                    raise ValueError("pbs_fingerprint deve essere SHA-256 (64 hex)")
        except Exception as e:
            return {
                "success": False, "backup_id": None,
                "message": f"Validazione input PBS fallita: {e}",
                "output": "", "error": str(e), "duration": 0,
            }

        # Se è specificato uno storage esistente, usalo; altrimenti crea/usa uno standard
        if pbs_storage_id:
            # Verifica che lo storage esista
            check_result = await ssh_service.execute(
                hostname=source_node_hostname,
                command=f"pvesm status 2>/dev/null | grep -q '^{pbs_storage_id} '",
                port=source_node_port,
                username=source_node_user,
                key_path=source_node_key
            )
            
            if check_result.exit_code != 0:
                return {
                    "success": False,
                    "backup_id": None,
                    "message": f"Storage PBS '{pbs_storage_id}' non trovato sul nodo",
                    "output": "",
                    "error": f"Storage {pbs_storage_id} non esiste",
                    "duration": 0
                }
            
            storage_name = pbs_storage_id
            logger.info(f"Using existing PBS storage: {storage_name}")
        else:
            # Crea storage PBS automaticamente o riusa esistente
            proposed_storage_name = f"pbs-{datastore}"
            
            storage_ok, actual_storage_name = await self._ensure_pbs_storage(
                node_hostname=source_node_hostname,
                storage_name=proposed_storage_name,
                pbs_hostname=pbs_hostname,
                datastore=datastore,
                pbs_user=pbs_user,
                pbs_password=pbs_password,
                pbs_fingerprint=pbs_fingerprint,
                node_port=source_node_port,
                node_user=source_node_user,
                node_key=source_node_key
            )
            
            if not storage_ok:
                return {
                    "success": False,
                    "backup_id": None,
                    "message": f"Impossibile configurare storage PBS: {actual_storage_name}",
                    "output": "",
                    "error": actual_storage_name,
                    "duration": 0
                }
            
            # Use the actual storage name returned (could be different if existing one was found)
            storage_name = actual_storage_name
        
        # storage_name puo' provenire da _ensure_pbs_storage; rivalido
        # difensivamente prima di costruire il comando.
        try:
            _check(storage_name, _PBS_STORAGE_RE, "storage_name")
        except Exception as e:
            return {
                "success": False, "backup_id": None,
                "message": f"Storage name non valido: {e}",
                "output": "", "error": str(e), "duration": 0,
            }

        # Setup comando backup vzdump (tutti i token validati)
        vzdump_parts = [
            "vzdump", str(vm_id_int),
            "--mode", mode,
            "--compress", compress,
            "--storage", storage_name,
            "--remove", "0"
        ]
        vzdump_cmd = " ".join(vzdump_parts)
        logger.info(f"Running backup: {vzdump_cmd}")
        
        result = await ssh_service.execute(
            hostname=source_node_hostname,
            command=vzdump_cmd,
            port=source_node_port,
            username=source_node_user,
            key_path=source_node_key,
            timeout=7200  # 2 ore timeout
        )
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        if result.success or "Backup job finished successfully" in result.stdout:
            # Cerca l'ID del backup dall'output
            backup_id = None
            # Pattern: backup started, backup finished, etc.
            backup_match = re.search(r"backup '(.+?)' successful", result.stdout) or \
                          re.search(r"creating vzdump archive '(.+?)'", result.stdout) or \
                          re.search(r"backup-id: '?([^'\n]+)'?", result.stdout)
            
            if backup_match:
                backup_id = backup_match.group(1)
            
            return {
                "success": True,
                "backup_id": backup_id,
                "message": f"Backup VM {vm_id} completato in {int(duration)}s",
                "output": result.stdout,
                "duration": int(duration)
            }
        else:
            return {
                "success": False,
                "backup_id": None,
                "message": f"Backup fallito: {result.stderr}",
                "output": result.stdout,
                "error": result.stderr,
                "duration": int(duration)
            }
    
    async def run_restore(
        self,
        dest_node_hostname: str,
        vm_id: int,
        pbs_hostname: str,
        datastore: str,
        backup_id: Optional[str] = None,  # None = usa l'ultimo
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        pbs_storage_id: Optional[str] = None,  # Nome storage PBS esistente sul nodo dest
        dest_vm_id: Optional[int] = None,  # None = stesso del sorgente
        dest_vm_name_suffix: Optional[str] = None,  # Suffisso nome VM (es: "-replica")
        dest_storage: Optional[str] = None,  # Storage target per i dischi
        vm_type: str = "qemu",
        start_vm: bool = False,
        unique: bool = True,  # Genera nuovi UUID
        overwrite: bool = True,
        dest_node_port: int = 22,
        dest_node_user: str = "root",
        dest_node_key: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """
        Ripristina una VM da PBS su un nodo destinazione.
        
        Args:
            dest_node_hostname: Hostname del nodo Proxmox VE destinazione
            vm_id: VMID della VM originale (per trovare il backup)
            pbs_hostname: Hostname del PBS server
            datastore: Nome del datastore PBS
            backup_id: ID specifico del backup (None = ultimo disponibile)
            dest_vm_id: VMID per la VM ripristinata (None = stesso del sorgente)
            dest_storage: Storage dove ripristinare i dischi
            vm_type: qemu o lxc
            start_vm: Avvia la VM dopo il restore
            unique: Genera nuovi UUID per i dischi
            overwrite: Sovrascrive se la VM esiste già
        
        Returns:
            Dict con success, message, output
        """
        start_time = datetime.utcnow()

        target_vmid = dest_vm_id or vm_id

        # Validazione difensiva: tutti gli input finiscono in qmrestore /
        # qm / pct / pvesm via SSH come root. Senza questi check siamo
        # vulnerabili a command injection da DB compromesso.
        try:
            vm_id_int = _check_int(vm_id, "vm_id")
            target_vmid_int = _check_int(target_vmid, "dest_vm_id")
            _check(dest_node_hostname, _PBS_HOST_RE, "dest_node_hostname")
            _check(pbs_hostname, _PBS_HOST_RE, "pbs_hostname")
            _check(datastore, _PBS_DATASTORE_RE, "datastore")
            _check(pbs_user, _PBS_USER_RE, "pbs_user")
            _check_in(vm_type, _PBS_VMTYPE_ALLOWED, "vm_type")
            if pbs_storage_id:
                _check(pbs_storage_id, _PBS_STORAGE_RE, "pbs_storage_id")
            if dest_storage:
                _check(dest_storage, _PBS_STORAGE_RE, "dest_storage")
            if backup_id:
                # Accettiamo "vm/100/2026-...Z" oppure il volid completo
                # con prefisso "<storage>:backup/...". Validiamo entrambi.
                if ":backup/" in backup_id:
                    storage_part, backup_part = backup_id.split(":", 1)
                    _check(storage_part, _PBS_STORAGE_RE, "backup_id storage")
                    if not re.fullmatch(r"backup/(?:vm|ct)/\d+/[0-9TZ:.\-]+", backup_part):
                        raise ValueError(f"backup_id volid non valido: {backup_id!r}")
                else:
                    _check(backup_id, _PBS_BACKUP_ID_RE, "backup_id")
            if dest_vm_name_suffix and not re.fullmatch(r"[A-Za-z0-9_\-]{1,50}", dest_vm_name_suffix):
                raise ValueError(f"dest_vm_name_suffix non valido: {dest_vm_name_suffix!r}")
            if pbs_fingerprint:
                fp = self._normalize_fingerprint(pbs_fingerprint)
                if not re.fullmatch(r"[0-9A-F]{64}", fp):
                    raise ValueError("pbs_fingerprint deve essere SHA-256 (64 hex)")
        except Exception as e:
            return {
                "success": False, "vm_id": target_vmid,
                "message": f"Validazione input PBS fallita: {e}",
                "output": "", "error": str(e), "duration": 0,
            }

        # Se è specificato uno storage esistente, usalo; altrimenti crea/usa uno standard
        if pbs_storage_id:
            # Verifica che lo storage esista sul nodo destinazione
            check_result = await ssh_service.execute(
                hostname=dest_node_hostname,
                command=f"pvesm status 2>/dev/null | grep -q '^{pbs_storage_id} '",
                port=dest_node_port,
                username=dest_node_user,
                key_path=dest_node_key
            )
            
            if check_result.exit_code != 0:
                return {
                    "success": False,
                    "vm_id": target_vmid,
                    "message": f"Storage PBS '{pbs_storage_id}' non trovato sul nodo destinazione",
                    "output": "",
                    "error": f"Storage {pbs_storage_id} non esiste su {dest_node_hostname}",
                    "duration": 0
                }
            
            storage_name = pbs_storage_id
            logger.info(f"Restore: using existing PBS storage: {storage_name}")
        else:
            # Crea storage PBS automaticamente
            storage_name = f"pbs-{datastore}"
            
            # Setup storage PBS sul nodo destinazione
            storage_ok, storage_msg = await self._ensure_pbs_storage(
                node_hostname=dest_node_hostname,
                storage_name=storage_name,
                pbs_hostname=pbs_hostname,
                datastore=datastore,
                pbs_user=pbs_user,
                pbs_password=pbs_password,
                pbs_fingerprint=pbs_fingerprint,
                node_port=dest_node_port,
                node_user=dest_node_user,
                node_key=dest_node_key
            )
            
            if not storage_ok:
                return {
                    "success": False,
                    "vm_id": target_vmid,
                    "message": f"Impossibile configurare storage PBS: {storage_msg}",
                    "output": "",
                    "error": storage_msg,
                    "duration": 0
                }
        
        # Se non abbiamo un backup_id specifico, trova l'ultimo
        if not backup_id:
            # Lista backup disponibili e prendi l'ultimo
            list_cmd = f"pvesm list {storage_name} --vmid {vm_id} 2>/dev/null | tail -n +2 | sort -k5 -r | head -1"
            list_result = await ssh_service.execute(
                hostname=dest_node_hostname,
                command=list_cmd,
                port=dest_node_port,
                username=dest_node_user,
                key_path=dest_node_key
            )
            
            if list_result.success and list_result.stdout.strip():
                # Parse volid dalla prima colonna
                parts = list_result.stdout.strip().split()
                if parts:
                    backup_id = parts[0]
            
            if not backup_id:
                return {
                    "success": False,
                    "message": f"Nessun backup trovato per VM {vm_id}",
                    "output": "",
                    "duration": 0
                }
        
        # Se esiste già la VM e overwrite è True, rimuovila prima
        if overwrite:
            check_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} status {target_vmid} 2>/dev/null"
            check_result = await ssh_service.execute(
                hostname=dest_node_hostname,
                command=check_cmd,
                port=dest_node_port,
                username=dest_node_user,
                key_path=dest_node_key
            )
            
            if check_result.success and ("running" in check_result.stdout or "stopped" in check_result.stdout):
                # Stop e destroy VM esistente
                destroy_cmd = f"""
{'qm' if vm_type == 'qemu' else 'pct'} stop {target_vmid} 2>/dev/null || true
sleep 2
{'qm' if vm_type == 'qemu' else 'pct'} destroy {target_vmid} --purge 2>/dev/null || true
"""
                await ssh_service.execute(
                    hostname=dest_node_hostname,
                    command=destroy_cmd,
                    port=dest_node_port,
                    username=dest_node_user,
                    key_path=dest_node_key,
                    timeout=120
                )
        
        # Build restore command (tutti i token validati a inizio funzione).
        # Per LXC il comando e' `pct restore`. backup_id deve essere il
        # volid (storage:backup/...) per qmrestore/pct restore.
        if vm_type == "lxc":
            restore_cmd = f"pct restore {target_vmid_int} {backup_id}"
        else:
            restore_cmd = f"qmrestore {backup_id} {target_vmid_int}"

        if dest_storage:
            restore_cmd += f" --storage {dest_storage}"

        if unique:
            restore_cmd += " --unique"

        if start_vm:
            restore_cmd += " --start"
        
        # Esegui restore
        result = await ssh_service.execute(
            hostname=dest_node_hostname,
            command=restore_cmd,
            port=dest_node_port,
            username=dest_node_user,
            key_path=dest_node_key,
            timeout=7200  # 2 ore
        )
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        if result.success or "successfully" in result.stdout.lower():
            # Applica suffisso al nome VM se specificato
            new_vm_name = None
            if dest_vm_name_suffix:
                # Ottieni nome corrente
                get_name_cmd = f"qm config {target_vmid} 2>/dev/null | grep '^name:' | cut -d' ' -f2"
                name_result = await ssh_service.execute(
                    hostname=dest_node_hostname,
                    command=get_name_cmd,
                    port=dest_node_port,
                    username=dest_node_user,
                    key_path=dest_node_key
                )
                
                if name_result.success and name_result.stdout.strip():
                    current_name = name_result.stdout.strip()
                    # Sanitize: solo caratteri DNS-safe nel nome finale.
                    normalized_suffix = dest_vm_name_suffix.replace('_', '-')
                    if normalized_suffix in current_name or dest_vm_name_suffix in current_name:
                        new_vm_name = current_name
                    else:
                        new_vm_name = f"{current_name}{normalized_suffix}"
                    new_vm_name = re.sub(r"[^A-Za-z0-9.\-]", "-", new_vm_name)[:63]

                    # Rinomina VM (nome whitelisted)
                    rename_cmd = f"qm set {target_vmid_int} --name '{new_vm_name}'"
                    logger.info(f"Renaming VM {target_vmid}: {rename_cmd}")
                    rename_result = await ssh_service.execute(
                        hostname=dest_node_hostname,
                        command=rename_cmd,
                        port=dest_node_port,
                        username=dest_node_user,
                        key_path=dest_node_key
                    )
                    
                    if rename_result.success or rename_result.exit_code == 0:
                        logger.info(f"VM {target_vmid} renamed to {new_vm_name}")
                    else:
                        logger.error(f"Failed to rename VM {target_vmid}: {rename_result.stderr or rename_result.stdout}")
                        # Don't fail the whole restore, just log the warning
                        new_vm_name = None
            
            return {
                "success": True,
                "vm_id": target_vmid,
                "vm_name": new_vm_name,
                "backup_id": backup_id,
                "message": f"Restore VM {target_vmid} completato in {int(duration)}s",
                "output": result.stdout,
                "duration": int(duration)
            }
        else:
            return {
                "success": False,
                "vm_id": target_vmid,
                "backup_id": backup_id,
                "message": f"Restore fallito: {result.stderr}",
                "output": result.stdout,
                "error": result.stderr,
                "duration": int(duration)
            }
    
    async def run_full_recovery(
        self,
        source_node_hostname: str,
        vm_id: int,
        pbs_hostname: str,
        datastore: str,
        dest_node_hostname: str,
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        pbs_storage_id: Optional[str] = None,  # Nome storage PBS esistente
        dest_vm_id: Optional[int] = None,
        dest_vm_name_suffix: Optional[str] = None,  # Suffisso nome VM
        dest_storage: Optional[str] = None,
        vm_type: str = "qemu",
        backup_mode: str = "snapshot",
        backup_compress: str = "zstd",
        start_vm: bool = False,
        unique: bool = True,
        overwrite: bool = True,
        source_node_port: int = 22,
        source_node_user: str = "root",
        source_node_key: str = "/root/.ssh/id_rsa",
        dest_node_port: int = 22,
        dest_node_user: str = "root",
        dest_node_key: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """
        Esegue l'intero ciclo di recovery: backup -> restore -> registrazione.
        
        NOTA: Questa funzione è mantenuta per compatibilità, ma ora la sequenza
        dettagliata è gestita direttamente in execute_recovery_job_task con logging
        separato per ogni fase.
        
        Returns:
            Dict con success, phases (backup, restore), message, duration
        """
        start_time = datetime.utcnow()
        result = {
            "success": False,
            "phases": {
                "backup": None,
                "restore": None
            },
            "message": "",
            "duration": 0
        }
        
        # Phase 1: Backup
        logger.info(f"[PBS Service] Fase 1/2: Backup VM {vm_id} da {source_node_hostname} verso PBS {pbs_hostname}")
        backup_result = await self.run_backup(
            source_node_hostname=source_node_hostname,
            vm_id=vm_id,
            pbs_hostname=pbs_hostname,
            datastore=datastore,
            pbs_user=pbs_user,
            pbs_password=pbs_password,
            pbs_fingerprint=pbs_fingerprint,
            pbs_storage_id=pbs_storage_id,
            vm_type=vm_type,
            mode=backup_mode,
            compress=backup_compress,
            source_node_port=source_node_port,
            source_node_user=source_node_user,
            source_node_key=source_node_key
        )
        
        result["phases"]["backup"] = backup_result
        
        if not backup_result["success"]:
            result["message"] = f"Backup fallito: {backup_result.get('error', 'Unknown error')}"
            result["duration"] = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"[PBS Service] Recovery fallita nella fase backup: {backup_result.get('error')}")
            return result
        
        backup_id = backup_result.get("backup_id")
        logger.info(f"[PBS Service] ✓ Backup completato - ID: {backup_id}")
        logger.info(f"[PBS Service] Fase 2/2: Restore VM {vm_id} da PBS {pbs_hostname} verso {dest_node_hostname}")
        
        # Phase 2: Restore (solo se backup riuscito)
        restore_result = await self.run_restore(
            dest_node_hostname=dest_node_hostname,
            vm_id=vm_id,
            pbs_hostname=pbs_hostname,
            datastore=datastore,
            backup_id=backup_id,  # Usa backup_id dal backup appena completato
            pbs_user=pbs_user,
            pbs_password=pbs_password,
            pbs_fingerprint=pbs_fingerprint,
            pbs_storage_id=pbs_storage_id,  # Usa stesso storage del backup
            dest_vm_id=dest_vm_id,
            dest_vm_name_suffix=dest_vm_name_suffix,
            dest_storage=dest_storage,
            vm_type=vm_type,
            start_vm=start_vm,
            unique=unique,
            overwrite=overwrite,
            dest_node_port=dest_node_port,
            dest_node_user=dest_node_user,
            dest_node_key=dest_node_key
        )
        
        result["phases"]["restore"] = restore_result
        
        if not restore_result["success"]:
            result["message"] = f"Restore fallito: {restore_result.get('error', 'Unknown error')}"
            result["duration"] = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"[PBS Service] Recovery fallita nella fase restore: {restore_result.get('error')}")
            return result
        
        # Success!
        result["success"] = True
        result["message"] = f"Recovery VM {vm_id} completata con successo"
        result["duration"] = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"[PBS Service] ✓ Recovery completata in {result['duration']:.1f}s")
        
        return result


# Singleton
pbs_service = PBSService()

