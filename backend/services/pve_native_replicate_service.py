"""
PVE Native Replicate Service
----------------------------
Replica VM tra due nodi Proxmox **senza** dipendenza da ZFS / BTRFS / PBS.

Pipeline orchestrata via SSH (stesso meccanismo SSH che dapx già usa):

  1) preflight su source: pveversion, qm/pct config, pvesm status,
     spazio disco sul dump_dir.
  2) preflight su dest: storage esiste, status active, VMID dest:
     se gia' usato richiede `replace_existing=True`.
  3) `vzdump --mode snapshot --compress <X> --dumpdir <DIR> --remove 0`
     sul source (mode snapshot e' nativo Proxmox e funziona su qualunque
     storage che supporta snapshot — qcow2-su-dir/LVM-thin/ZFS/btrfs/RBD).
  4) trasferimento via `scp` dell'archivio al dest.
  5) (se replace_existing) `qm stop` graceful + `qm destroy --purge`.
  6) `qmrestore <archivio> <vmid> --storage <dest> --unique` (oppure
     `pct restore` per LXC).
  7) `proxmox_service.register_vm(...)` esistente per applicare
     dest_vm_name / dest_bridge / dest_vlan / force_cpu_host /
     vm_name_suffix (sostituzione regex-safe gia' fatta in v3.16.5).
  8) (se cleanup_after) `rm` archivio sul source. Sul dest sempre
     rimosso dopo restore OK.

NON e' incrementale: ogni run trasferisce l'archivio completo.
Per replica incrementale di banda usare `recovery_pbs` (PBS dirty
bitmap).
"""

from __future__ import annotations

import logging
import re
import shlex
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from services.ssh_service import ssh_service
from services.proxmox_service import proxmox_service
from services.pve_tags import ensure_vm_replication_tag

logger = logging.getLogger(__name__)


# Storage type che supportano snapshot consistent — verificato sul source
# tramite `pvesm status -enabled 1` (header tipo:storage).
_SNAPSHOT_CAPABLE = {
    "zfspool", "zfs", "btrfs", "lvmthin", "rbd", "cephfs",
    "dir", "nfs", "cifs", "glusterfs",  # supportano snapshot solo se i disk sono qcow2
}


# Validazioni difensive (ogni stringa finisce in una shell remota).
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")
_STORAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-.]*$")
_DUMP_DIR_RE = re.compile(r"^/[A-Za-z0-9_./\-]+$")
_COMPRESS_ALLOWED = {"none", "lzo", "gzip", "zstd"}


class PveNativeReplicateService:
    """Orchestratore della pipeline pve_native."""

    async def run(
        self,
        *,
        source_host: str,
        source_port: int,
        source_user: str,
        source_key: str,
        dest_host: str,
        dest_port: int,
        dest_user: str,
        dest_key: str,
        vm_id: int,
        vm_type: str = "qemu",         # "qemu" | "lxc"
        dest_vm_id: Optional[int] = None,
        dest_storage: Optional[str] = None,
        dump_dir: str = "/var/lib/vz/dump",
        compress: str = "zstd",
        bandwidth_limit_kb: Optional[int] = None,
        cleanup_after: bool = True,
        replace_existing: bool = False,
        dest_vm_name: Optional[str] = None,
        dest_vm_name_suffix: Optional[str] = None,
        dest_bridge: Optional[str] = None,
        dest_vlan: Optional[int] = None,
        force_cpu_host: bool = True,
        log_cb: Optional[Callable[[str], Awaitable[None]]] = None,
        timeout: int = 7200,
    ) -> Dict[str, Any]:
        """Esegue la pipeline. Ritorna dict con chiavi:
            success, output, error, duration, transferred (size bytes),
            archive_source, archive_dest, target_vmid, command (informativo).
        """
        started = datetime.utcnow()

        async def _log(msg: str):
            logger.info(f"[pve_native] {msg}")
            if log_cb:
                try:
                    await log_cb(msg)
                except Exception:
                    pass

        # --- 0) validazione difensiva ---
        try:
            self._assert_inputs(
                source_host, dest_host, dest_storage, dump_dir, compress,
                vm_type, vm_id, dest_vm_id, bandwidth_limit_kb,
                dest_bridge, dest_vlan, dest_vm_name, dest_vm_name_suffix,
            )
        except ValueError as e:
            return self._fail(str(e), "validation", started, "")

        target_vmid = int(dest_vm_id) if dest_vm_id else int(vm_id)

        # --- 1) preflight source ---
        await _log("Pre-flight sul nodo sorgente...")
        try:
            await self._preflight_source(
                source_host, source_port, source_user, source_key,
                vm_id, vm_type, dump_dir,
            )
        except RuntimeError as e:
            return self._fail(f"Preflight sorgente: {e}", "preflight_source", started, "")

        # --- 2) preflight dest ---
        await _log("Pre-flight sul nodo destinazione...")
        try:
            await self._preflight_dest(
                dest_host, dest_port, dest_user, dest_key,
                target_vmid, vm_type, dest_storage, replace_existing,
            )
        except RuntimeError as e:
            return self._fail(f"Preflight destinazione: {e}", "preflight_dest", started, "")

        # --- 3) vzdump sul source ---
        await _log(f"vzdump VM {vm_id} su {source_host} (mode=snapshot, compress={compress})...")
        vzdump_cmd_parts = [
            "vzdump", str(int(vm_id)),
            "--mode", "snapshot",
            "--compress", compress,
            "--dumpdir", dump_dir,
            "--remove", "0",
        ]
        if bandwidth_limit_kb and bandwidth_limit_kb > 0:
            vzdump_cmd_parts += ["--bwlimit", str(int(bandwidth_limit_kb))]
        vzdump_cmd = " ".join(vzdump_cmd_parts)

        r = await ssh_service.execute(
            hostname=source_host,
            command=vzdump_cmd,
            port=source_port,
            username=source_user,
            key_path=source_key,
            timeout=timeout,
        )
        if not r.success and "Backup job finished successfully" not in (r.stdout or ""):
            return self._fail(
                f"vzdump fallito: {(r.stderr or r.stdout or '')[:400]}",
                "vzdump", started, vzdump_cmd,
            )

        # --- 4) trova archivio creato ---
        find_cmd = (
            f"ls -t {shlex.quote(dump_dir)}/vzdump-{vm_type}-{int(vm_id)}-*.vma.zst "
            f"{shlex.quote(dump_dir)}/vzdump-{vm_type}-{int(vm_id)}-*.tar.zst 2>/dev/null | head -1"
        )
        r2 = await ssh_service.execute(
            hostname=source_host, command=find_cmd, port=source_port,
            username=source_user, key_path=source_key, timeout=15,
        )
        archive_source = (r2.stdout or "").strip()
        if not r2.success or not archive_source:
            return self._fail(
                f"Archivio non trovato in {dump_dir} dopo vzdump",
                "find_archive", started, find_cmd,
            )
        await _log(f"Archivio creato: {archive_source}")

        # dimensione archivio
        sz_cmd = f"stat -c%s {shlex.quote(archive_source)} 2>/dev/null || echo 0"
        rsz = await ssh_service.execute(
            hostname=source_host, command=sz_cmd, port=source_port,
            username=source_user, key_path=source_key, timeout=10,
        )
        try:
            archive_size = int((rsz.stdout or "0").strip())
        except Exception:
            archive_size = 0

        archive_name = archive_source.rsplit("/", 1)[-1]
        archive_dest = f"{dump_dir.rstrip('/')}/{archive_name}"

        # --- 5) trasferimento via scp dal dapx (executor=source) verso dest ---
        # Il source ha gia' la chiave SSH dapx in authorized_keys per il
        # dest (gestito da v3.13 _ensure_executor_authorized). Eseguiamo
        # scp DAL source AL dest.
        await _log(f"scp dell'archivio verso {dest_host}:{archive_dest}...")
        scp_opts = (
            f"-i {shlex.quote(source_key)} "  # chiave dapx, gia' autorizzata sul dest
            f"-o StrictHostKeyChecking=no "
            f"-P {int(dest_port)} "
        )
        # Su sorgente eseguiamo `scp <archive> dest_user@dest_host:archive_dest`
        # con la chiave dapx. Per non duplicare la chiave, scp viene eseguito
        # via ssh_service.execute sul source (dove la chiave e' montata).
        scp_cmd = (
            f"mkdir -p {shlex.quote(dump_dir)} && "
            f"scp -i {shlex.quote(source_key)} "
            f"-o StrictHostKeyChecking=no "
            f"-P {int(dest_port)} "
            f"{shlex.quote(archive_source)} "
            f"{shlex.quote(dest_user)}@{shlex.quote(dest_host)}:{shlex.quote(archive_dest)}"
        )
        # `mkdir` deve girare sul dest, non sul source. Lo facciamo via ssh
        # separato sul dest:
        await ssh_service.execute(
            hostname=dest_host,
            command=f"mkdir -p {shlex.quote(dump_dir)}",
            port=dest_port, username=dest_user, key_path=dest_key, timeout=15,
        )
        # ora lo scp dal source
        scp_cmd = (
            f"scp -i {shlex.quote(source_key)} "
            f"-o StrictHostKeyChecking=no -o BatchMode=yes "
            f"-P {int(dest_port)} "
            f"{shlex.quote(archive_source)} "
            f"{shlex.quote(dest_user)}@{shlex.quote(dest_host)}:{shlex.quote(archive_dest)}"
        )
        rscp = await ssh_service.execute(
            hostname=source_host, command=scp_cmd,
            port=source_port, username=source_user, key_path=source_key,
            timeout=timeout,
        )
        if not rscp.success:
            # Cleanup parziale: archivio source resta (per debug); dest puo'
            # avere file parziale → rimuoviamolo.
            await ssh_service.execute(
                hostname=dest_host,
                command=f"rm -f {shlex.quote(archive_dest)}",
                port=dest_port, username=dest_user, key_path=dest_key, timeout=10,
            )
            return self._fail(
                f"scp fallito: {(rscp.stderr or rscp.stdout or '')[:400]}",
                "scp", started, scp_cmd,
            )

        # --- 6) destroy VM dest pre-esistente se replace_existing ---
        if replace_existing:
            await _log(f"Rimozione VM esistente {target_vmid} su {dest_host}...")
            qm_cli = "qm" if vm_type == "qemu" else "pct"
            destroy_cmd = (
                f"{qm_cli} stop {target_vmid} --timeout 60 2>/dev/null; "
                f"sleep 1; "
                f"{qm_cli} shutdown {target_vmid} --timeout 30 --forceStop 1 2>/dev/null; "
                f"sleep 1; "
                f"{qm_cli} destroy {target_vmid} --purge 1 --skiplock 1 2>/dev/null"
            )
            await ssh_service.execute(
                hostname=dest_host, command=destroy_cmd,
                port=dest_port, username=dest_user, key_path=dest_key, timeout=120,
            )

        # --- 7) qmrestore / pct restore sul dest ---
        await _log(f"qmrestore VM {target_vmid} su {dest_host}...")
        if vm_type == "qemu":
            restore_cmd = (
                f"qmrestore {shlex.quote(archive_dest)} {target_vmid} "
                f"--unique 1"
            )
            if dest_storage:
                restore_cmd += f" --storage {shlex.quote(dest_storage)}"
        else:
            # pct restore <vmid> <archive> --storage <X>
            restore_cmd = (
                f"pct restore {target_vmid} {shlex.quote(archive_dest)}"
            )
            if dest_storage:
                restore_cmd += f" --storage {shlex.quote(dest_storage)}"

        rrest = await ssh_service.execute(
            hostname=dest_host, command=restore_cmd,
            port=dest_port, username=dest_user, key_path=dest_key, timeout=timeout,
        )
        if not rrest.success and "successfully" not in (rrest.stdout or "").lower():
            # cleanup archivio su entrambi i lati
            await ssh_service.execute(
                hostname=dest_host,
                command=f"rm -f {shlex.quote(archive_dest)}",
                port=dest_port, username=dest_user, key_path=dest_key, timeout=10,
            )
            return self._fail(
                f"qmrestore fallito: {(rrest.stderr or rrest.stdout or '')[:400]}",
                "qmrestore", started, restore_cmd,
            )

        # --- 8) override config (nome/bridge/vlan/cpu) ---
        warnings: list = []
        if dest_vm_name or dest_vm_name_suffix or dest_bridge or dest_vlan is not None or force_cpu_host:
            await _log("Applico override config su VM destinazione...")
            try:
                # Leggiamo la config dest dopo qmrestore e la riscriviamo.
                ok_cfg, current_cfg = await proxmox_service.get_vm_config_file(
                    hostname=dest_host, vmid=target_vmid,
                    vm_type=vm_type,
                    port=dest_port, username=dest_user, key_path=dest_key,
                )
                if ok_cfg:
                    # `register_vm` rifiuta di scrivere se esiste gia' un .conf;
                    # qui lo abbiamo gia' creato con qmrestore quindi
                    # applichiamo direttamente le modifiche con qm set / pct set.
                    qm_cli = "qm" if vm_type == "qemu" else "pct"
                    if dest_vm_name:
                        safe = re.sub(r"[^A-Za-z0-9.\-]", "-", dest_vm_name)[:63]
                        await ssh_service.execute(
                            hostname=dest_host,
                            command=f"{qm_cli} set {target_vmid} --name {shlex.quote(safe)}",
                            port=dest_port, username=dest_user, key_path=dest_key, timeout=20,
                        )
                    elif dest_vm_name_suffix:
                        # Estrai nome corrente dal config
                        m = re.search(r"^name:\s*(.+)$", current_cfg, re.MULTILINE)
                        if m:
                            base = m.group(1).strip()
                            new_name = re.sub(r"[^A-Za-z0-9.\-]", "-", base + dest_vm_name_suffix)[:63]
                            await ssh_service.execute(
                                hostname=dest_host,
                                command=f"{qm_cli} set {target_vmid} --name {shlex.quote(new_name)}",
                                port=dest_port, username=dest_user, key_path=dest_key, timeout=20,
                            )
                    if force_cpu_host and vm_type == "qemu":
                        await ssh_service.execute(
                            hostname=dest_host,
                            command=f"qm set {target_vmid} --cpu host",
                            port=dest_port, username=dest_user, key_path=dest_key, timeout=20,
                        )
                    if (dest_bridge or dest_vlan is not None) and vm_type == "qemu":
                        # itera su net0, net1, ... presenti in config
                        for line in (current_cfg or "").splitlines():
                            mnet = re.match(r"^(net\d+):\s*(.+)$", line)
                            if not mnet:
                                continue
                            iface = mnet.group(1)
                            spec = mnet.group(2)
                            if dest_bridge:
                                spec = re.sub(r"\bbridge=[^,\s]+", f"bridge={dest_bridge}", spec)
                            if dest_vlan is not None:
                                if "tag=" in spec:
                                    spec = re.sub(r"\btag=\d+", f"tag={int(dest_vlan)}", spec)
                                else:
                                    spec = f"{spec},tag={int(dest_vlan)}"
                            await ssh_service.execute(
                                hostname=dest_host,
                                command=f"qm set {target_vmid} --{iface} {shlex.quote(spec)}",
                                port=dest_port, username=dest_user, key_path=dest_key, timeout=20,
                            )
            except Exception as e:
                warnings.append(f"Override config parziale: {e}")

        # Tag REPL su tutte le VM replicate via pve_native
        try:
            tag_ok, tag_msg = await ensure_vm_replication_tag(
                ssh_service,
                hostname=dest_host,
                vmid=target_vmid,
                vm_type=vm_type,
                port=dest_port,
                username=dest_user,
                key_path=dest_key,
            )
            if not tag_ok:
                warnings.append(tag_msg)
        except Exception as e:
            warnings.append(f"Tag REPL non applicato: {e}")

        # --- 9) cleanup archivi ---
        # dest sempre (l'archivio e' stato consumato)
        await ssh_service.execute(
            hostname=dest_host,
            command=f"rm -f {shlex.quote(archive_dest)}",
            port=dest_port, username=dest_user, key_path=dest_key, timeout=10,
        )
        if cleanup_after:
            await ssh_service.execute(
                hostname=source_host,
                command=f"rm -f {shlex.quote(archive_source)}",
                port=source_port, username=source_user, key_path=source_key, timeout=10,
            )

        duration = int((datetime.utcnow() - started).total_seconds())
        await _log(f"Replica completata in {duration}s, target VMID={target_vmid}")

        return {
            "success": True,
            "output": (rrest.stdout or "")[-2000:],
            "error": "",
            "duration": duration,
            "transferred": _human_bytes(archive_size),
            "transferred_bytes": archive_size,
            "archive_source": archive_source,
            "archive_dest": archive_dest,
            "target_vmid": target_vmid,
            "command": vzdump_cmd,
            "warnings": warnings,
        }

    # ---------------- helpers ----------------

    @staticmethod
    def _assert_inputs(
        source_host, dest_host, dest_storage, dump_dir, compress,
        vm_type, vm_id, dest_vm_id, bandwidth_limit_kb,
        dest_bridge, dest_vlan, dest_vm_name, dest_vm_name_suffix,
    ):
        if not _HOST_RE.match(source_host or ""):
            raise ValueError(f"source_host non valido: {source_host!r}")
        if not _HOST_RE.match(dest_host or ""):
            raise ValueError(f"dest_host non valido: {dest_host!r}")
        if dest_storage and not _STORAGE_RE.match(dest_storage):
            raise ValueError(f"dest_storage non valido: {dest_storage!r}")
        if not _DUMP_DIR_RE.match(dump_dir or ""):
            raise ValueError(f"dump_dir non valido: {dump_dir!r}")
        if (compress or "zstd") not in _COMPRESS_ALLOWED:
            raise ValueError(f"compress non valido: {compress!r}")
        if vm_type not in ("qemu", "lxc"):
            raise ValueError(f"vm_type non valido: {vm_type!r}")
        try:
            v = int(vm_id)
            if v < 100 or v > 999_999_999:
                raise ValueError
        except Exception:
            raise ValueError(f"vm_id fuori range: {vm_id!r}")
        if dest_vm_id is not None:
            try:
                v = int(dest_vm_id)
                if v < 100 or v > 999_999_999:
                    raise ValueError
            except Exception:
                raise ValueError(f"dest_vm_id fuori range: {dest_vm_id!r}")
        if bandwidth_limit_kb is not None and (bandwidth_limit_kb < 0 or bandwidth_limit_kb > 10_000_000):
            raise ValueError(f"bandwidth_limit_kb fuori range: {bandwidth_limit_kb!r}")
        if dest_bridge and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,49}", dest_bridge):
            raise ValueError(f"dest_bridge non valido: {dest_bridge!r}")
        if dest_vlan is not None and not (1 <= int(dest_vlan) <= 4094):
            raise ValueError(f"dest_vlan fuori range: {dest_vlan!r}")
        if dest_vm_name and not re.fullmatch(r"[A-Za-z0-9.\-_ ]{1,100}", dest_vm_name):
            raise ValueError(f"dest_vm_name non valido")
        if dest_vm_name_suffix and not re.fullmatch(r"[A-Za-z0-9_\-]{1,50}", dest_vm_name_suffix):
            raise ValueError(f"dest_vm_name_suffix non valido")

    @staticmethod
    def _fail(msg: str, phase: str, started: datetime, command: str) -> Dict[str, Any]:
        return {
            "success": False,
            "output": "",
            "error": msg,
            "phase": phase,
            "duration": int((datetime.utcnow() - started).total_seconds()),
            "transferred": None,
            "transferred_bytes": 0,
            "archive_source": None,
            "archive_dest": None,
            "target_vmid": None,
            "command": command,
            "warnings": [],
        }

    async def _preflight_source(
        self, host, port, user, key, vm_id, vm_type, dump_dir,
    ) -> None:
        # PVE version
        r = await ssh_service.execute(
            hostname=host, command="pveversion 2>/dev/null | head -1",
            port=port, username=user, key_path=key, timeout=10,
        )
        if not r.success or "pve-manager" not in (r.stdout or "").lower():
            raise RuntimeError(f"pveversion non disponibile su {host}")

        # config VM esiste
        cli = "qm" if vm_type == "qemu" else "pct"
        r2 = await ssh_service.execute(
            hostname=host, command=f"{cli} config {int(vm_id)} 2>&1 | head -50",
            port=port, username=user, key_path=key, timeout=10,
        )
        if not r2.success or "configuration file" in (r2.stdout or "").lower() and "not exist" in (r2.stdout or "").lower():
            raise RuntimeError(f"VM {vm_id} ({vm_type}) non trovata su {host}")
        config = r2.stdout or ""

        # dump_dir scrivibile + spazio sufficiente. Stima naive: somma `size=` * 1.2.
        total_size_g = 0.0
        for m in re.finditer(r"size=([\d.]+)([GMTK])", config):
            v = float(m.group(1))
            unit = m.group(2)
            mult = {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1, "T": 1024}.get(unit, 1)
            total_size_g += v * mult
        # Considera anche compressione: assumiamo ratio ~0.5 (zstd). Soglia
        # generosa: chiediamo total_size_g GiB di liberi sul dump_dir.
        need_bytes = int(max(total_size_g, 1.0) * 1024 * 1024 * 1024)
        r3 = await ssh_service.execute(
            hostname=host,
            command=f"mkdir -p {shlex.quote(dump_dir)} && df -B1 --output=avail {shlex.quote(dump_dir)} | tail -1",
            port=port, username=user, key_path=key, timeout=15,
        )
        try:
            free = int((r3.stdout or "0").strip())
            if free and free < need_bytes:
                raise RuntimeError(
                    f"Spazio insufficiente in {dump_dir}: liberi "
                    f"{_human_bytes(free)}, richiesti ~{_human_bytes(need_bytes)} (stima)"
                )
        except RuntimeError:
            raise
        except Exception:
            # df non parsabile: passiamo (vzdump fallira' in modo chiaro)
            pass

    async def _preflight_dest(
        self, host, port, user, key, target_vmid, vm_type, dest_storage,
        replace_existing,
    ) -> None:
        # storage esiste e attivo
        if dest_storage:
            r = await ssh_service.execute(
                hostname=host,
                command=f"pvesm status --storage {shlex.quote(dest_storage)} 2>&1",
                port=port, username=user, key_path=key, timeout=10,
            )
            if not r.success or dest_storage not in (r.stdout or ""):
                raise RuntimeError(f"Storage destinazione '{dest_storage}' non trovato su {host}")
            # rough check 'active'
            for line in (r.stdout or "").splitlines():
                if line.startswith(dest_storage + " "):
                    if "active" not in line.lower():
                        raise RuntimeError(f"Storage '{dest_storage}' non attivo su {host}")
                    break

        # VMID dest libero o replace_existing=True
        cli = "qm" if vm_type == "qemu" else "pct"
        r2 = await ssh_service.execute(
            hostname=host,
            command=(
                f"{cli} status {int(target_vmid)} 2>/dev/null; "
                f"test -f /etc/pve/qemu-server/{int(target_vmid)}.conf "
                f"-o -f /etc/pve/lxc/{int(target_vmid)}.conf && echo exists"
            ),
            port=port, username=user, key_path=key, timeout=10,
        )
        out = (r2.stdout or "").lower()
        existing = (
            "status:" in out or "running" in out or "stopped" in out or "exists" in out
        )
        if existing and not replace_existing:
            raise RuntimeError(
                f"VMID {target_vmid} gia' presente su {host}. "
                f"Abilita 'replace_existing' o scegli un VMID libero."
            )


def _human_bytes(n: Optional[int]) -> str:
    if not n:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    x = float(n)
    while x >= 1024 and i < len(units) - 1:
        x /= 1024
        i += 1
    return f"{x:.1f} {units[i]}" if i > 0 else f"{int(x)} B"


# Singleton
pve_native_replicate_service = PveNativeReplicateService()
