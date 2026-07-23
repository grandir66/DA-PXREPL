"""Esecuzione job sync (syncoid/BTRFS/PVE native) e monitoraggio."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from database import SyncJob
from services.btrfs_service import btrfs_service
from services.scheduler import scheduler_service
from services.syncoid_service import syncoid_service
from services.vm_group_sync_service import (
    continue_vm_group_chain as _continue_vm_group_chain,
    vm_group_sync_complete as _vm_group_sync_complete,
)

logger = logging.getLogger(__name__)

_vm_register_inflight: set[str] = set()


async def send_job_notification_helper(
    job_id: int,
    job_name: str,
    status: str,
    source: str,
    destination: str,
    duration: int = None,
    error: str = None,
    details: str = None,
    is_scheduled: bool = False,
    notify_mode: str = "daily",
    source_node_name: str = None,
    dest_node_name: str = None,
    job_type: str = "sync",
    vm_name: str = None,
    vm_id: int = None,
    transferred: str = None,
    notify_subject: str = None,
):
    """
    Invia notifica per un job di replica usando il notification_service centralizzato.
    
    notify_mode controlla quando inviare:
    - 'always': sempre
    - 'daily': max 1 al giorno per successi
    - 'failure': solo errori
    - 'never': mai
    """
    from services.notification_service import notification_service
    
    await notification_service.send_job_notification(
        job_name=job_name,
        status=status,
        source=source,
        destination=destination,
        duration=duration,
        error=error,
        details=details[:1000] if details else None,
        job_id=job_id,
        is_scheduled=is_scheduled,
        notify_mode=notify_mode,
        job_type=job_type,
        source_node_name=source_node_name,
        dest_node_name=dest_node_name,
        vm_name=vm_name,
        vm_id=vm_id,
        transferred=transferred,
        notify_subject=notify_subject,
    )


# ============== Helper Function per esecuzione job ==============

async def _persist_sync_progress(
    job_id: int,
    log_entry_id: int,
    progress: Dict[str, Any],
) -> None:
    """Salva avanzamento replica nel log e nel job (best-effort)."""
    from database import SessionLocal, SyncJob, JobLog

    ts = datetime.utcnow().strftime("%H:%M:%S")
    line = (
        f"[{ts}] Avanzamento: {progress['percent']}% "
        f"({progress['dest_human']} scritti su {progress['source_human']} sorgente)"
    )
    db = SessionLocal()
    try:
        job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
        log = db.query(JobLog).filter(JobLog.id == log_entry_id).first()
        if job:
            job.last_transferred = progress["label"]
        if log:
            prev = log.output or ""
            if line not in prev:
                log.output = prev + ("\n" if prev else "") + line
        db.commit()
    except Exception as e:
        logger.debug(f"persist progress job {job_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


async def _poll_sync_progress(
    stop_event: asyncio.Event,
    job_id: int,
    log_entry_id: int,
    source_node,
    dest_node,
    source_dataset: str,
    dest_dataset: str,
    interval: int = 30,
) -> None:
    """Polling ogni `interval` secondi del rapporto used/refer ZFS."""
    while not stop_event.is_set():
        try:
            progress = await syncoid_service.get_replication_progress(
                executor_host=source_node.hostname,
                executor_port=source_node.ssh_port,
                executor_user=source_node.ssh_user,
                executor_key=source_node.ssh_key_path,
                source_dataset=source_dataset,
                dest_host=dest_node.hostname,
                dest_port=dest_node.ssh_port,
                dest_user=dest_node.ssh_user,
                dest_key=dest_node.ssh_key_path,
                dest_dataset=dest_dataset,
            )
            if progress:
                await _persist_sync_progress(job_id, log_entry_id, progress)
        except Exception as e:
            logger.debug(f"poll progress job {job_id}: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            continue


def _dest_zfs_pool_for_job(job: SyncJob) -> str:
    """Pool/dataset Proxmox per i volumi replicati (es. ZFS-LARGE/replica)."""
    parts = (job.dest_dataset or "").split("/")
    if len(parts) >= 2:
        return "/".join(parts[:-1])
    return parts[0] if parts else ""


async def _try_register_vm_after_sync(job_id: int, log_entry_id: int) -> None:
    """Registra la VM su Proxmox quando la sync (e tutti i dischi gemelli) sono OK."""
    from database import SessionLocal, SyncJob, Node, JobLog, SyncMethod
    from services.proxmox_service import proxmox_service
    from services.ssh_service import ssh_service

    db = SessionLocal()
    reg_key = None
    try:
        job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
        log = db.query(JobLog).filter(JobLog.id == log_entry_id).first()
        if not job or not log:
            return
        if not job.register_vm or not job.vm_id:
            return
        sync_method = job.sync_method or SyncMethod.SYNCOID.value
        if sync_method in (SyncMethod.BTRFS_SEND.value, SyncMethod.PVE_NATIVE.value):
            return
        if (job.last_status or "").lower() != "success":
            return
        if not _vm_group_sync_complete(db, job):
            note = " | Registrazione VM in attesa: sync di tutti i dischi del gruppo non completata"
            if note not in (log.message or ""):
                log.message = (log.message or "") + note
                db.commit()
            return

        target_vmid = job.dest_vm_id or job.vm_id
        reg_key = f"{job.dest_node_id}:{target_vmid}"
        if reg_key in _vm_register_inflight:
            return
        _vm_register_inflight.add(reg_key)

        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
        if not source_node or not dest_node:
            return

        vm_type = job.vm_type or "qemu"
        config_path = (
            f"/etc/pve/qemu-server/{job.vm_id}.conf"
            if vm_type == "qemu"
            else f"/etc/pve/lxc/{job.vm_id}.conf"
        )
        config_result = await ssh_service.execute(
            hostname=source_node.hostname,
            command=f"cat {config_path} 2>/dev/null",
            port=source_node.ssh_port,
            username=source_node.ssh_user,
            key_path=source_node.ssh_key_path,
            timeout=30,
        )
        if not config_result.success or not config_result.stdout.strip():
            log.message = (log.message or "") + " | Config VM non trovata su sorgente"
            db.commit()
            return

        dest_zfs_pool = _dest_zfs_pool_for_job(job)
        try:
            dest_bridges = await proxmox_service.get_node_bridges(
                hostname=dest_node.hostname,
                port=dest_node.ssh_port,
                username=dest_node.ssh_user,
                key_path=dest_node.ssh_key_path,
            )
        except Exception:
            dest_bridges = None

        success, msg, warnings = await proxmox_service.register_vm(
            hostname=dest_node.hostname,
            vmid=target_vmid,
            vm_type=vm_type,
            config_content=config_result.stdout,
            source_storage=job.source_storage,
            dest_storage=job.dest_storage,
            dest_zfs_pool=dest_zfs_pool,
            vm_name_suffix=job.dest_vm_name_suffix,
            new_name=getattr(job, "dest_vm_name", None),
            force_cpu_host=bool(getattr(job, "force_cpu_host", True)),
            dest_node_bridges=dest_bridges,
            dest_bridge=getattr(job, "dest_bridge", None),
            dest_vlan=getattr(job, "dest_vlan", None),
            port=dest_node.ssh_port,
            username=dest_node.ssh_user,
            key_path=dest_node.ssh_key_path,
        )

        if success:
            vm_info = f"VM {target_vmid}" + (
                f" (da {job.vm_id})" if target_vmid != job.vm_id else ""
            )
            log.message = (log.message or "") + f" | {vm_info} registrata su {dest_node.name}"
            if warnings:
                log.message += f" [Avvisi: {'; '.join(warnings)}]"
        else:
            log.message = (log.message or "") + f" | Registrazione VM fallita: {msg}"
        db.commit()
    except Exception as e:
        logger.warning(f"Registrazione VM post-sync job {job_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if reg_key:
            _vm_register_inflight.discard(reg_key)
        db.close()


def repair_terminal_job_log(log, job) -> bool:
    """Allinea status del log se completed_at è valorizzato ma lo status è ancora aperto."""
    status = (log.status or "").lower()
    if status in ("success", "failed"):
        return False
    if not log.completed_at:
        return False
    job_status = (job.last_status or "").lower() if job else ""
    if job_status in ("success", "failed"):
        log.status = job_status
    elif log.error:
        log.status = "failed"
    else:
        log.status = "success"
    note = " [status corretto automaticamente]"
    if note not in (log.message or ""):
        log.message = (log.message or "") + note
    return True


async def _apply_sync_monitor_timeout(
    job_id: int,
    log_entry_id: int,
    still_active: bool,
) -> None:
    """Segna failed un job syncoid il cui monitor ha esaurito il budget (~6h)."""
    from database import SessionLocal, SyncJob, JobLog

    db = SessionLocal()
    try:
        job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
        log = db.query(JobLog).filter(JobLog.id == log_entry_id).first()
        if not job or not log or log.completed_at:
            return
        log.status = "failed"
        log.completed_at = datetime.utcnow()
        suffix = (
            " | Monitor timeout (~6h) — replica ancora attiva sui nodi"
            if still_active
            else " | Monitor timeout (~6h) — replica non più rilevata"
        )
        log.message = (log.message or "") + suffix
        log.error = (log.error or "") + "Monitor timeout (~6h)"
        job.last_status = "failed"
        if hasattr(job, "current_status"):
            try:
                job.current_status = "idle"
            except Exception:
                pass
        job.error_count = (job.error_count or 0) + 1
        job.consecutive_failures = (job.consecutive_failures or 0) + 1
        job.last_run = datetime.utcnow()
        db.commit()
    except Exception as e:
        logger.warning(f"Timeout monitor job {job_id} fallito: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


async def _finalize_sync_job(
    job_id: int,
    log_entry_id: int,
    dest_node,
    dest_dataset: str,
    job_key: str,
) -> bool:
    """Chiude job/log quando la replica non è più attiva sui nodi."""
    from database import SessionLocal, SyncJob, JobLog
    from services.ssh_service import ssh_service

    db = SessionLocal()
    try:
        job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
        log = db.query(JobLog).filter(JobLog.id == log_entry_id).first()
        if not job or not log:
            return False
        if log.completed_at:
            repair_terminal_job_log(log, job)
            if hasattr(job, "current_status"):
                try:
                    job.current_status = "idle"
                except Exception:
                    pass
            if (job.last_status or "").lower() == "running":
                ls = (log.status or "").lower()
                job.last_status = ls if ls in ("success", "failed") else "success"
            db.commit()
            return (log.status or "").lower() == "success"

        check = await ssh_service.execute(
            hostname=dest_node.hostname,
            command=f"zfs list -H -o name {dest_dataset} 2>&1",
            port=dest_node.ssh_port,
            username=dest_node.ssh_user,
            key_path=dest_node.ssh_key_path,
            timeout=20,
        )
        ok = check.success and dest_dataset in (check.stdout or "")
        job.last_status = "success" if ok else "failed"
        if hasattr(job, "current_status"):
            try:
                job.current_status = "idle"
            except Exception:
                pass
        if not ok:
            job.error_count += 1
            job.consecutive_failures += 1
        else:
            job.consecutive_failures = 0
            job.run_count += 1
        job.last_run = datetime.utcnow()
        log.status = "success" if ok else "failed"
        log.completed_at = datetime.utcnow()
        log.message = (
            (log.message or "")
            + (" | Replica completata" if ok else " | Replica terminata — verifica dataset/log syncoid")
        )
        if not ok:
            log.error = (log.error or "") + (check.stderr or check.stdout or "")
        db.commit()
        if ok:
            await _try_register_vm_after_sync(job_id, log_entry_id)
            db2 = SessionLocal()
            try:
                job2 = db2.query(SyncJob).filter(SyncJob.id == job_id).first()
                if job2 and job2.vm_group_id:
                    asyncio.create_task(_continue_vm_group_chain(job2.vm_group_id))
            finally:
                db2.close()
        return ok
    except Exception as e:
        logger.warning(f"Finalize job {job_id} fallito: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return False
    finally:
        db.close()
        scheduler_service.mark_done(job_key)


async def _monitor_sync_job_completion(
    job_id: int,
    job_key: str,
    log_entry_id: int,
    source_node,
    dest_node,
    source_dataset: str,
    dest_dataset: str,
):
    """Attende fine syncoid/receive remoto e aggiorna stato job."""
    import asyncio as _asyncio
    from database import SessionLocal, SyncJob, Node

    # Nodi possono arrivare da sessioni DB già chiuse (reconcile startup).
    db_boot = SessionLocal()
    try:
        job_boot = db_boot.query(SyncJob).filter(SyncJob.id == job_id).first()
        if job_boot:
            source_node = (
                db_boot.query(Node).filter(Node.id == job_boot.source_node_id).first()
                or source_node
            )
            dest_node = (
                db_boot.query(Node).filter(Node.id == job_boot.dest_node_id).first()
                or dest_node
            )
            source_dataset = job_boot.source_dataset
            dest_dataset = job_boot.dest_dataset
    finally:
        db_boot.close()

    if not source_node or not dest_node:
        scheduler_service.mark_done(job_key)
        return

    try:
        for _ in range(720):  # max ~6h @ 30s
            active = await syncoid_service.is_replication_active(
                executor_host=source_node.hostname,
                executor_port=source_node.ssh_port,
                executor_user=source_node.ssh_user,
                executor_key=source_node.ssh_key_path,
                source_dataset=source_dataset,
                dest_host=dest_node.hostname,
                dest_port=dest_node.ssh_port,
                dest_user=dest_node.ssh_user,
                dest_key=dest_node.ssh_key_path,
                dest_dataset=dest_dataset,
            )
            if active:
                progress = await syncoid_service.get_replication_progress(
                    executor_host=source_node.hostname,
                    executor_port=source_node.ssh_port,
                    executor_user=source_node.ssh_user,
                    executor_key=source_node.ssh_key_path,
                    source_dataset=source_dataset,
                    dest_host=dest_node.hostname,
                    dest_port=dest_node.ssh_port,
                    dest_user=dest_node.ssh_user,
                    dest_key=dest_node.ssh_key_path,
                    dest_dataset=dest_dataset,
                )
                if progress:
                    await _persist_sync_progress(job_id, log_entry_id, progress)
                await _asyncio.sleep(30)
                continue

            await _finalize_sync_job(
                job_id, log_entry_id, dest_node, dest_dataset, job_key
            )
            return

        still_active = await syncoid_service.is_replication_active(
            executor_host=source_node.hostname,
            executor_port=source_node.ssh_port,
            executor_user=source_node.ssh_user,
            executor_key=source_node.ssh_key_path,
            source_dataset=source_dataset,
            dest_host=dest_node.hostname,
            dest_port=dest_node.ssh_port,
            dest_user=dest_node.ssh_user,
            dest_key=dest_node.ssh_key_path,
            dest_dataset=dest_dataset,
        )
        if still_active:
            await _apply_sync_monitor_timeout(job_id, log_entry_id, still_active=True)
        else:
            await _finalize_sync_job(
                job_id, log_entry_id, dest_node, dest_dataset, job_key
            )
    except Exception as e:
        logger.warning(f"Monitor job {job_id} interrotto: {e}")
    finally:
        scheduler_service.mark_done(job_key)
async def execute_sync_job_task(job_id: int, triggered_by_user_id: int = None) -> bool:
    """
    Esegue un job di sync. Ritorna True se il lock scheduler va tenuto
    (replica ancora attiva sui nodi, monitor in background).
    """
    from database import SessionLocal, SyncJob, Node, JobLog, SyncMethod
    from services.syncoid_service import syncoid_service
    from services.btrfs_service import btrfs_service
    from services.ssh_service import ssh_service
    import traceback
    
    db_session = SessionLocal()
    log_entry = None
    job_record = None
    
    try:
        # Recupera job e nodi dal database
        job = db_session.query(SyncJob).filter(SyncJob.id == job_id).first()
        if not job:
            return False
        
        source_node = db_session.query(Node).filter(Node.id == job.source_node_id).first()
        dest_node = db_session.query(Node).filter(Node.id == job.dest_node_id).first()
        
        if not source_node or not dest_node:
            return False
        
        # Determina il tipo di job
        sync_method = job.sync_method or SyncMethod.SYNCOID.value
        if sync_method == SyncMethod.BTRFS_SEND.value:
            job_type = "sync_btrfs"
        elif sync_method == SyncMethod.PVE_NATIVE.value:
            job_type = "sync_pve_native"
        else:
            job_type = "sync"
        
        # Crea log entry. Inizializziamo `output` con un header
        # informativo cosi' il viewer di /progress vede subito qualcosa
        # invece di "Nessun log" durante il run lungo (vzdump/syncoid
        # scrivono solo a fine, e il polling incrementale appende
        # progress messages via log_cb).
        from datetime import datetime as _dt
        _t0 = _dt.utcnow().strftime("%H:%M:%S")
        _initial_output = (
            f"[{_t0}] Job avviato — metodo={sync_method}\n"
            f"[{_t0}] Source: {source_node.name} ({source_node.hostname})\n"
            f"[{_t0}] Dest:   {dest_node.name} ({dest_node.hostname})\n"
        )
        log_entry = JobLog(
            job_type=job_type,
            job_id=job_id,
            node_name=f"{source_node.name} -> {dest_node.name}",
            dataset=f"{job.source_dataset} -> {job.dest_dataset}",
            status="started",
            output=_initial_output,
            triggered_by=triggered_by_user_id
        )
        db_session.add(log_entry)
        db_session.commit()
        db_session.refresh(log_entry)

        # Aggiorna stato
        job_record = db_session.query(SyncJob).filter(SyncJob.id == job_id).first()
        job_record.last_status = "running"
        if hasattr(job_record, "current_status"):
            try:
                job_record.current_status = "running"
            except Exception:
                pass
        db_session.commit()
        
        # Esegui sync in base al metodo
        if sync_method == SyncMethod.PVE_NATIVE.value:
            # ============== PVE NATIVE (vzdump+scp+qmrestore) ==============
            # Replica VM senza dipendenza da ZFS/BTRFS/PBS. Funziona su
            # qualunque storage che supporta snapshot (qcow2-su-dir,
            # LVM-thin, RBD/Ceph, ZFS, btrfs). NON e' incrementale: ogni
            # run trasferisce l'archivio completo.
            from services.pve_native_replicate_service import pve_native_replicate_service

            # Callback live: ogni progress message viene appeso a
            # JobLog.output con un commit, cosi' il viewer di /progress
            # vede l'avanzamento in tempo reale (polling 1.5s).
            # NB: usa una sessione DB dedicata per evitare race con la
            # transazione principale del task in background.
            _log_id = log_entry.id
            async def _live_log_cb(msg: str):
                from datetime import datetime as _dt
                from database import SessionLocal as _SL
                ts = _dt.utcnow().strftime("%H:%M:%S")
                line = f"[{ts}] {msg}"
                _s = _SL()
                try:
                    le = _s.query(JobLog).filter(JobLog.id == _log_id).first()
                    if le is not None:
                        prev = le.output or ""
                        le.output = (prev + ("\n" if prev else "") + line)
                        _s.commit()
                except Exception:
                    try:
                        _s.rollback()
                    except Exception:
                        pass
                finally:
                    try:
                        _s.close()
                    except Exception:
                        pass

            result = await pve_native_replicate_service.run(
                source_host=source_node.hostname,
                source_port=source_node.ssh_port,
                source_user=source_node.ssh_user,
                source_key=source_node.ssh_key_path,
                dest_host=dest_node.hostname,
                dest_port=dest_node.ssh_port,
                dest_user=dest_node.ssh_user,
                dest_key=dest_node.ssh_key_path,
                vm_id=job.vm_id or 0,
                vm_type=job.vm_type or "qemu",
                dest_vm_id=job.dest_vm_id,
                dest_storage=job.dest_storage,
                dump_dir=job.dump_dir or "/var/lib/vz/dump",
                compress=job.pve_compress or "zstd",
                bandwidth_limit_kb=job.bandwidth_limit_kb,
                cleanup_after=bool(job.cleanup_after) if job.cleanup_after is not None else True,
                replace_existing=bool(job.replace_existing),
                dest_vm_name=job.dest_vm_name,
                dest_vm_name_suffix=job.dest_vm_name_suffix,
                dest_bridge=job.dest_bridge,
                dest_vlan=job.dest_vlan,
                force_cpu_host=bool(job.force_cpu_host) if job.force_cpu_host is not None else True,
                log_cb=_live_log_cb,
            )
            # transferred mappato per coerenza con altri metodi
            if result.get("warnings"):
                log_entry.message = (log_entry.message or "") + (
                    f" | Avvisi: {'; '.join(result['warnings'])[:200]}"
                )

        elif sync_method == SyncMethod.BTRFS_SEND.value:
            # ============== BTRFS SYNC ==============
            # Determina directory snapshot
            snapshot_dir = job.btrfs_snapshot_dir or source_node.btrfs_snapshot_dir or f"{source_node.btrfs_mount}/.snapshots"
            dest_snapshot_dir = job.btrfs_dest_snapshot_dir or dest_node.btrfs_snapshot_dir or f"{dest_node.btrfs_mount}/.snapshots"
            
            result = await btrfs_service.run_sync(
                executor_host=source_node.hostname,
                disk_path=job.source_dataset,  # Per BTRFS è il path del disco
                vmid=job.vm_id or 0,
                disk_name=job.disk_name or "disk",
                snapshot_dir=snapshot_dir,
                dest_host=dest_node.hostname,
                dest_snapshot_dir=dest_snapshot_dir,
                full_sync=job.btrfs_full_sync,
                executor_port=source_node.ssh_port,
                executor_user=source_node.ssh_user,
                executor_key=source_node.ssh_key_path,
                dest_port=dest_node.ssh_port,
                dest_user=dest_node.ssh_user,
                dest_key=dest_node.ssh_key_path,
                max_snapshots=job.btrfs_max_snapshots or 5,
                timeout=3600
            )
            
            # Aggiorna sync type per BTRFS
            job_record.last_sync_type = result.get("sync_type")
            
        else:
            # ============== ZFS/SYNCOID SYNC ==============
            # Crea dataset parent sulla destinazione se non esiste
            dest_parent = "/".join(job.dest_dataset.split("/")[:-1])
            if dest_parent:
                check_result = await ssh_service.execute(
                    hostname=dest_node.hostname,
                    command=f"zfs list -H -o name {dest_parent} 2>/dev/null || echo 'NOT_EXISTS'",
                    port=dest_node.ssh_port,
                    username=dest_node.ssh_user,
                    key_path=dest_node.ssh_key_path,
                    timeout=30
                )
                
                if "NOT_EXISTS" in check_result.stdout or not check_result.success:
                    create_result = await ssh_service.execute(
                        hostname=dest_node.hostname,
                        command=f"zfs create -p {dest_parent}",
                        port=dest_node.ssh_port,
                        username=dest_node.ssh_user,
                        key_path=dest_node.ssh_key_path,
                        timeout=30
                    )
                    if create_result.success:
                        log_entry.message = f"Creato dataset parent: {dest_parent}"
                    else:
                        log_entry.message = f"Attenzione: impossibile creare {dest_parent}: {create_result.stderr}"
            
            # Esegui sync ZFS (con polling avanzamento ogni 30s)
            stop_progress = asyncio.Event()
            progress_task = asyncio.create_task(
                _poll_sync_progress(
                    stop_progress,
                    job_id,
                    log_entry.id,
                    source_node,
                    dest_node,
                    job.source_dataset,
                    job.dest_dataset,
                )
            )
            try:
                result = await syncoid_service.run_sync(
                    executor_host=source_node.hostname,
                    source_host=None,
                    source_dataset=job.source_dataset,
                    dest_host=dest_node.hostname,
                    dest_dataset=job.dest_dataset,
                    dest_user=dest_node.ssh_user,
                    dest_port=dest_node.ssh_port,
                    dest_key=dest_node.ssh_key_path,
                    executor_port=source_node.ssh_port,
                    executor_user=source_node.ssh_user,
                    executor_key=source_node.ssh_key_path,
                    recursive=job.recursive,
                    compress=job.compress or "lz4",
                    mbuffer_size=job.mbuffer_size or "128M",
                    no_sync_snap=job.no_sync_snap,
                    force_delete=job.force_delete,
                    extra_args=job.extra_args or ""
                )
            finally:
                stop_progress.set()
                try:
                    await asyncio.wait_for(progress_task, timeout=5)
                except Exception:
                    progress_task.cancel()
            
            # Se retention configurata, crea snapshot backup_* sulla destinazione DOPO il sync
            use_retention = job.keep_snapshots and job.keep_snapshots > 0
            
            if use_retention and result["success"]:
                # Crea snapshot backup_* sulla destinazione (non tocca le snapshot syncoid_*)
                timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H:%M:%S")
                backup_snap_name = f"backup_{timestamp}"
                backup_snap = f"{job.dest_dataset}@{backup_snap_name}"
                
                create_snap_cmd = f"zfs snapshot {backup_snap}"
                snap_result = await ssh_service.execute(
                    hostname=dest_node.hostname,
                    command=create_snap_cmd,
                    port=dest_node.ssh_port,
                    username=dest_node.ssh_user,
                    key_path=dest_node.ssh_key_path,
                    timeout=60
                )
                
                if not snap_result.success:
                    logger.warning(f"Errore creazione snapshot retention: {snap_result.stderr}")
                
                # Lista snapshot backup_* sulla destinazione e applica retention
                list_cmd = f"zfs list -t snapshot -o name -s creation -H {job.dest_dataset} 2>/dev/null | grep '@backup_' || true"
                list_result = await ssh_service.execute(
                    hostname=dest_node.hostname,
                    command=list_cmd,
                    port=dest_node.ssh_port,
                    username=dest_node.ssh_user,
                    key_path=dest_node.ssh_key_path,
                    timeout=60
                )
                
                if list_result.success and list_result.stdout.strip():
                    snapshots = [s.strip() for s in list_result.stdout.strip().split('\n') if s.strip()]
                    
                    # Se abbiamo più snapshot del limite, elimina le più vecchie
                    if len(snapshots) > job.keep_snapshots:
                        to_delete = snapshots[:-job.keep_snapshots]
                        deleted_count = 0
                        
                        for snap in to_delete:
                            del_cmd = f"zfs destroy {snap}"
                            del_result = await ssh_service.execute(
                                hostname=dest_node.hostname,
                                command=del_cmd,
                                port=dest_node.ssh_port,
                                username=dest_node.ssh_user,
                                key_path=dest_node.ssh_key_path,
                                timeout=60
                            )
                            if del_result.success:
                                deleted_count += 1
                        
                        if deleted_count > 0:
                            result["retention_deleted"] = deleted_count
        
        # Aggiorna job e log
        if result.get("still_running"):
            # Transfer ancora in corso sui nodi: non marcare failed.
            job_record.last_status = "running"
            if hasattr(job_record, "current_status"):
                try:
                    job_record.current_status = "running"
                except Exception:
                    pass
            log_entry.status = "started"
            note = (
                "Replica ancora in esecuzione sui nodi sorgente/destinazione "
                "(syncoid o zfs receive attivo). "
                "Il monitoraggio continuerà fino al completamento."
            )
            err_hint = (result.get("error") or "").strip()
            if err_hint:
                note += f"\nNota syncoid: {err_hint[:500]}"
            log_entry.message = (log_entry.message or "") + (" | " if log_entry.message else "") + note
            if result.get("output"):
                prev = log_entry.output or ""
                sep = "\n--- output ---\n" if prev else ""
                log_entry.output = prev + sep + result["output"]
            db_session.commit()
            job_key = f"sync_{job_id}"
            asyncio.create_task(
                _monitor_sync_job_completion(
                    job_id=job_id,
                    job_key=job_key,
                    log_entry_id=log_entry.id,
                    source_node=source_node,
                    dest_node=dest_node,
                    source_dataset=job.source_dataset,
                    dest_dataset=job.dest_dataset,
                )
            )
            return True

        job_record.last_run = datetime.utcnow()
        job_record.last_duration = result["duration"]
        job_record.last_transferred = result.get("transferred")
        job_record.run_count += 1
        
        if result["success"]:
            job_record.last_status = "success"
            if hasattr(job_record, "current_status"):
                try:
                    job_record.current_status = "idle"
                except Exception:
                    pass
            job_record.consecutive_failures = 0
            log_entry.status = "success"
            log_entry.message = (log_entry.message or "") + " Sincronizzazione completata"
            await _try_register_vm_after_sync(job_id, log_entry.id)
            
            # Log retention info
            if use_retention:
                deleted = result.get("retention_deleted", 0)
                if deleted > 0:
                    log_entry.message += f" | Retention: {job.keep_snapshots} versioni (eliminate {deleted})"
                else:
                    log_entry.message += f" | Retention: {job.keep_snapshots} versioni"
        else:
            job_record.last_status = "failed"
            if hasattr(job_record, "current_status"):
                try:
                    job_record.current_status = "idle"
                except Exception:
                    pass
            job_record.error_count += 1
            job_record.consecutive_failures += 1
            log_entry.status = "failed"
            error_msg = result.get("error", "")
            if result.get("output") and "error" in result.get("output", "").lower():
                error_msg = f"{error_msg}\n\nOutput:\n{result.get('output')}" if error_msg else result.get("output")
            error_msg = f"Comando: {result.get('command', 'N/A')}\n\n{error_msg}" if error_msg else f"Comando: {result.get('command', 'N/A')}\nErrore sconosciuto"
            log_entry.error = error_msg
        
        # Append dell'output finale al log progressivo (prodotto da
        # log_cb durante la run). Senza append, perderemmo i progress
        # message scritti incrementalmente.
        _final_out = result.get("output") or ""
        if _final_out:
            # Refresha per leggere progress eventualmente scritti dal callback
            db_session.refresh(log_entry)
            prev = log_entry.output or ""
            sep = "\n--- output ---\n" if prev and not prev.endswith("\n--- output ---\n") else ""
            log_entry.output = prev + sep + _final_out
        log_entry.duration = result["duration"]
        log_entry.transferred = result.get("transferred")
        log_entry.completed_at = datetime.utcnow()
        
        db_session.commit()
        
        # Invia notifica se configurata
        try:
            await send_job_notification_helper(
                job_id=job_id,
                job_name=job.name,
                status="success" if result["success"] else "failed",
                source=f"{source_node.name}:{job.source_dataset}",
                destination=f"{dest_node.name}:{job.dest_dataset}",
                duration=result["duration"],
                error=result.get("error") if not result["success"] else None,
                details=result.get("output"),
                is_scheduled=False,
                notify_mode=job.notify_mode or "daily",
                source_node_name=source_node.name,
                dest_node_name=dest_node.name,
                job_type="sync",
                vm_name=getattr(job, "vm_name", None),
                vm_id=getattr(job, "vm_id", None),
                transferred=result.get("transferred"),
                notify_subject=getattr(job, "notify_subject", None),
            )
        except Exception as notify_err:
            # Non bloccare se la notifica fallisce
            logging.getLogger(__name__).warning(f"Errore invio notifica: {notify_err}")
        
        return False
        
    except Exception as e:
        # Se la replica e' ancora attiva sui nodi, non segnare failed.
        still_active = False
        try:
            if (
                job_record
                and source_node
                and dest_node
                and (job_record.sync_method or SyncMethod.SYNCOID.value) not in (
                    SyncMethod.BTRFS_SEND.value,
                    SyncMethod.PVE_NATIVE.value,
                )
            ):
                still_active = await syncoid_service.is_replication_active(
                    executor_host=source_node.hostname,
                    executor_port=source_node.ssh_port,
                    executor_user=source_node.ssh_user,
                    executor_key=source_node.ssh_key_path,
                    source_dataset=job_record.source_dataset,
                    dest_host=dest_node.hostname,
                    dest_port=dest_node.ssh_port,
                    dest_user=dest_node.ssh_user,
                    dest_key=dest_node.ssh_key_path,
                    dest_dataset=job_record.dest_dataset,
                )
        except Exception:
            still_active = False

        if still_active and log_entry and job_record:
            job_record.last_status = "running"
            if hasattr(job_record, "current_status"):
                try:
                    job_record.current_status = "running"
                except Exception:
                    pass
            log_entry.message = (
                (log_entry.message or "")
                + " | Eccezione lato manager ma replica ancora attiva sui nodi"
            )
            db_session.commit()
            job_key = f"sync_{job_id}"
            asyncio.create_task(
                _monitor_sync_job_completion(
                    job_id=job_id,
                    job_key=job_key,
                    log_entry_id=log_entry.id,
                    source_node=source_node,
                    dest_node=dest_node,
                    source_dataset=job_record.source_dataset,
                    dest_dataset=job_record.dest_dataset,
                )
            )
            return True

        if log_entry:
            log_entry.status = "failed"
            log_entry.error = f"Eccezione Python: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            log_entry.completed_at = datetime.utcnow()
        
        if job_record:
            try:
                job_record.last_status = "failed"
                if hasattr(job_record, "current_status"):
                    try:
                        job_record.current_status = "idle"
                    except Exception:
                        pass
                job_record.error_count += 1
                job_record.consecutive_failures += 1
            except:
                pass
        
        try:
            db_session.commit()
        except:
            pass
        return False
    finally:
        db_session.close()


async def _run_sync_job_background(job_id: int, job_key: str, triggered_by_user_id: int = None):
    """Avvia execute_sync_job_task in background; rilascia lock se il job termina qui."""
    keep_lock = False
    try:
        keep_lock = await execute_sync_job_task(job_id, triggered_by_user_id)
    finally:
        if not keep_lock:
            scheduler_service.mark_done(job_key)
