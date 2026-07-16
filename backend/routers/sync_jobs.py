"""
Router per gestione job di sincronizzazione Syncoid/BTRFS
Con autenticazione e autorizzazione
Supporta sia ZFS (syncoid) che BTRFS (btrfs send/receive)
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel
import re
import asyncio
import logging

from database import get_db, Node, SyncJob, JobLog, User, SyncMethod
from services.syncoid_service import syncoid_service
from services.btrfs_service import btrfs_service
from services.scheduler import scheduler_service
from services.schedule_helpers import resolve_schedule_pair
from services.vm_group_sync_service import (
    vm_group_key as _vm_group_key,
    vm_group_sync_complete as _vm_group_sync_complete,
    continue_vm_group_chain as _continue_vm_group_chain,
    run_vm_group_background as _run_vm_group_background,
)
from services.sync_job_live_state import (
    get_sync_job_live_state as _get_sync_job_live_state,
    compute_vm_group_progress as _compute_vm_group_progress,
)
from routers.auth import get_current_user, require_operator, require_admin, log_audit

logger = logging.getLogger(__name__)


def _resolve_schedule_pair(schedule: Optional[str], schedule_config: Optional[Dict[str, Any]]):
    try:
        return resolve_schedule_pair(schedule, schedule_config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"schedule_config non valido: {e}")

router = APIRouter()


# ============== Helper Function per notifiche ==============

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
    job_type: str = "sync"
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
        dest_node_name=dest_node_name
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


_vm_register_inflight: set[str] = set()


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
            if hasattr(job, "current_status"):
                try:
                    job.current_status = "idle"
                except Exception:
                    pass
            if (job.last_status or "").lower() == "running":
                job.last_status = log.status or "success"
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
    except Exception as e:
        logger.warning(f"Monitor job {job_id} interrotto: {e}")
    finally:
        scheduler_service.mark_done(job_key)


async def _reconcile_running_sync_jobs_once() -> None:
    """Periodicamente: chiude job completati o riavvia monitor caduti."""
    from database import SessionLocal, SyncJob, Node, JobLog, SyncMethod

    db = SessionLocal()
    try:
        jobs = db.query(SyncJob).filter(SyncJob.last_status == "running").all()
        for job in jobs:
            sync_method = job.sync_method or SyncMethod.SYNCOID.value
            if sync_method in (SyncMethod.BTRFS_SEND.value, SyncMethod.PVE_NATIVE.value):
                continue
            source = db.query(Node).filter(Node.id == job.source_node_id).first()
            dest = db.query(Node).filter(Node.id == job.dest_node_id).first()
            if not source or not dest:
                continue
            try:
                active = await syncoid_service.is_replication_active(
                    executor_host=source.hostname,
                    executor_port=source.ssh_port,
                    executor_user=source.ssh_user,
                    executor_key=source.ssh_key_path,
                    source_dataset=job.source_dataset,
                    dest_host=dest.hostname,
                    dest_port=dest.ssh_port,
                    dest_user=dest.ssh_user,
                    dest_key=dest.ssh_key_path,
                    dest_dataset=job.dest_dataset,
                )
            except Exception:
                active = False

            log = (
                db.query(JobLog)
                .filter(JobLog.job_id == job.id)
                .order_by(JobLog.started_at.desc())
                .first()
            )
            if not log:
                continue

            job_key = f"sync_{job.id}"
            if not active:
                if not log.completed_at:
                    await _finalize_sync_job(
                        job.id, log.id, dest, job.dest_dataset, job_key
                    )
                continue

            if scheduler_service.is_running(job_key):
                continue

            scheduler_service.mark_running(job_key)
            asyncio.create_task(
                _monitor_sync_job_completion(
                    job_id=job.id,
                    job_key=job_key,
                    log_entry_id=log.id,
                    source_node=source,
                    dest_node=dest,
                    source_dataset=job.source_dataset,
                    dest_dataset=job.dest_dataset,
                )
            )
            logger.info(f"Reconcile: monitor riavviato per job {job.id}")
    except Exception as e:
        logger.warning(f"Reconcile running sync jobs fallito: {e}")
    finally:
        db.close()


async def reconcile_pending_vm_registrations() -> None:
    """Registra VM mancanti per job già in success (es. completati via monitor)."""
    from database import SessionLocal, SyncJob, Node, JobLog
    from services.ssh_service import ssh_service

    db = SessionLocal()
    try:
        jobs = db.query(SyncJob).filter(
            SyncJob.last_status == "success",
            SyncJob.register_vm == True,  # noqa: E712
            SyncJob.vm_id.isnot(None),
        ).all()
        for job in jobs:
            if not _vm_group_sync_complete(db, job):
                continue
            target_vmid = job.dest_vm_id or job.vm_id
            dest = db.query(Node).filter(Node.id == job.dest_node_id).first()
            if not dest:
                continue
            vm_type = job.vm_type or "qemu"
            conf = (
                f"/etc/pve/qemu-server/{target_vmid}.conf"
                if vm_type == "qemu"
                else f"/etc/pve/lxc/{target_vmid}.conf"
            )
            exists = await ssh_service.execute(
                hostname=dest.hostname,
                command=f"test -f {conf} && echo yes",
                port=dest.ssh_port,
                username=dest.ssh_user,
                key_path=dest.ssh_key_path,
                timeout=15,
            )
            if "yes" in (exists.stdout or ""):
                continue
            log = (
                db.query(JobLog)
                .filter(JobLog.job_id == job.id)
                .order_by(JobLog.started_at.desc())
                .first()
            )
            if not log:
                continue
            if "registrata" in (log.message or ""):
                continue
            await _try_register_vm_after_sync(job.id, log.id)
    except Exception as e:
        logger.warning(f"Reconcile registrazioni VM pendenti fallito: {e}")
    finally:
        db.close()


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
                job_type="sync"
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


# ============== Schemas ==============

class SyncJobCreate(BaseModel):
    name: Optional[str] = None  # Se non fornito, viene generato automaticamente
    source_node_id: int
    source_dataset: str
    dest_node_id: int
    dest_dataset: str
    dest_subfolder: Optional[str] = None
    
    # Sync method: syncoid (ZFS) or btrfs_send (BTRFS)
    sync_method: str = "syncoid"  # syncoid | btrfs_send
    
    # ZFS/Syncoid options
    recursive: bool = False
    compress: str = "lz4"
    mbuffer_size: str = "128M"
    no_sync_snap: bool = False
    force_delete: bool = False
    extra_args: Optional[str] = None
    
    # BTRFS options
    btrfs_snapshot_dir: Optional[str] = None
    btrfs_dest_snapshot_dir: Optional[str] = None
    btrfs_max_snapshots: int = 5
    btrfs_full_sync: bool = False
    
    # Scheduling
    schedule: Optional[str] = None  # cron format
    schedule_config: Optional[Dict[str, Any]] = None  # struttura "human" (vedi schedule_translator)

    # VM options
    register_vm: bool = False
    vm_id: Optional[int] = None
    dest_vm_id: Optional[int] = None  # ID VM destinazione (se diverso da sorgente)
    vm_type: Optional[str] = None
    vm_name: Optional[str] = None
    dest_vm_name: Optional[str] = None  # Override completo nome VM (precede suffix)
    dest_vm_name_suffix: Optional[str] = None  # Suffisso per nome VM su destinazione (es: -replica)
    dest_bridge: Optional[str] = None  # Bridge dest (sostituisce bridge=... nelle righe netN)
    dest_vlan: Optional[int] = None    # VLAN tag dest (1-4094)
    disk_name: Optional[str] = None  # Nome disco (per BTRFS)
    force_cpu_host: bool = True  # Forza CPU type a 'host' su destinazione per compatibilità

    # Parametri sync_method=pve_native
    dump_dir: Optional[str] = None
    bandwidth_limit_kb: Optional[int] = None
    pve_compress: Optional[str] = None
    cleanup_after: Optional[bool] = None
    replace_existing: Optional[bool] = None
    
    # Notifiche
    notify_mode: str = "daily"  # daily, always, failure, never
    notify_subject: Optional[str] = None
    
    # Retention - snapshot da mantenere sulla destinazione
    keep_snapshots: int = 0  # 0 = solo ultima, N = mantieni ultime N
    
    # Retry
    retry_on_failure: bool = True
    max_retries: int = 3


class SyncJobUpdate(BaseModel):
    name: Optional[str] = None
    source_node_id: Optional[int] = None  # Permetti cambio nodo sorgente
    source_dataset: Optional[str] = None
    dest_node_id: Optional[int] = None  # Permetti cambio nodo destinazione
    dest_dataset: Optional[str] = None
    dest_subfolder: Optional[str] = None
    sync_method: Optional[str] = None
    
    # ZFS options
    recursive: Optional[bool] = None
    compress: Optional[str] = None
    mbuffer_size: Optional[str] = None
    no_sync_snap: Optional[bool] = None
    force_delete: Optional[bool] = None
    extra_args: Optional[str] = None
    
    # BTRFS options
    btrfs_snapshot_dir: Optional[str] = None
    btrfs_dest_snapshot_dir: Optional[str] = None
    btrfs_max_snapshots: Optional[int] = None
    btrfs_full_sync: Optional[bool] = None
    
    schedule: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    register_vm: Optional[bool] = None
    vm_id: Optional[int] = None
    dest_vm_id: Optional[int] = None
    vm_type: Optional[str] = None
    vm_name: Optional[str] = None
    dest_vm_name: Optional[str] = None  # Override completo nome VM
    dest_vm_name_suffix: Optional[str] = None  # Suffisso per nome VM su destinazione
    dest_bridge: Optional[str] = None
    dest_vlan: Optional[int] = None
    disk_name: Optional[str] = None
    force_cpu_host: Optional[bool] = None  # Forza CPU type a 'host' su destinazione
    source_storage: Optional[str] = None  # Storage Proxmox sorgente
    dest_storage: Optional[str] = None  # Storage Proxmox destinazione
    # pve_native
    dump_dir: Optional[str] = None
    bandwidth_limit_kb: Optional[int] = None
    pve_compress: Optional[str] = None
    cleanup_after: Optional[bool] = None
    replace_existing: Optional[bool] = None
    
    # Notifiche
    notify_mode: Optional[str] = None  # daily, always, failure, never
    notify_subject: Optional[str] = None
    
    # Retention
    keep_snapshots: Optional[int] = None  # 0 = solo ultima, N = mantieni ultime N
    
    retry_on_failure: Optional[bool] = None
    max_retries: Optional[int] = None
    retry_delay_minutes: Optional[int] = None


class SyncJobResponse(BaseModel):
    id: int
    name: str
    sync_method: Optional[str] = "syncoid"
    source_node_id: int
    source_dataset: str
    dest_node_id: int
    dest_dataset: str
    dest_subfolder: Optional[str] = None
    
    # ZFS options
    recursive: bool
    compress: Optional[str]
    mbuffer_size: Optional[str]
    no_sync_snap: bool
    force_delete: bool
    extra_args: Optional[str]
    
    # BTRFS options
    btrfs_snapshot_dir: Optional[str] = None
    btrfs_dest_snapshot_dir: Optional[str] = None
    btrfs_max_snapshots: Optional[int] = 5
    btrfs_full_sync: Optional[bool] = False

    # pve_native options
    dump_dir: Optional[str] = None
    bandwidth_limit_kb: Optional[int] = None
    pve_compress: Optional[str] = None
    cleanup_after: Optional[bool] = None
    replace_existing: Optional[bool] = None
    
    schedule: Optional[str]
    schedule_config: Optional[Dict[str, Any]] = None
    is_active: bool
    register_vm: bool
    vm_id: Optional[int]
    dest_vm_id: Optional[int]
    vm_type: Optional[str]
    vm_name: Optional[str]
    dest_vm_name: Optional[str] = None
    dest_vm_name_suffix: Optional[str] = None
    dest_bridge: Optional[str] = None
    dest_vlan: Optional[int] = None
    force_cpu_host: Optional[bool] = True
    vm_group_id: Optional[str]
    disk_name: Optional[str]
    source_storage: Optional[str] = None
    dest_storage: Optional[str] = None
    
    # Notifiche
    notify_mode: Optional[str] = "daily"  # daily, always, failure, never
    notify_subject: Optional[str] = None
    
    # Retention
    keep_snapshots: Optional[int] = 0  # 0 = solo ultima, N = mantieni ultime N
    
    retry_on_failure: bool
    max_retries: int
    last_run: Optional[datetime]
    last_status: Optional[str]
    current_status: Optional[str] = None
    last_duration: Optional[int]
    last_transferred: Optional[str]
    last_sync_type: Optional[str] = None  # full/incremental per BTRFS
    run_count: int
    error_count: int
    consecutive_failures: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class SyncJobResponseWithNodes(SyncJobResponse):
    source_node_name: Optional[str] = None
    dest_node_name: Optional[str] = None
    is_replicating: bool = False
    transfer_progress: Optional[Dict[str, Any]] = None
    group_transfer_progress: Optional[Dict[str, Any]] = None
    group_disks_done: Optional[int] = None
    group_disks_total: Optional[int] = None
    group_is_running: bool = False


# ============== Helper Functions ==============

async def reconcile_sync_jobs_after_restart() -> None:
    """Allinea DB e riavvia monitor per replica ancora attiva dopo restart backend."""
    from database import SessionLocal, SyncJob, Node, SyncMethod

    db = SessionLocal()
    try:
        jobs = db.query(SyncJob).filter(SyncJob.last_status == "failed").all()
        for job in jobs:
            sync_method = job.sync_method or SyncMethod.SYNCOID.value
            if sync_method in (SyncMethod.BTRFS_SEND.value, SyncMethod.PVE_NATIVE.value):
                continue
            source = db.query(Node).filter(Node.id == job.source_node_id).first()
            dest = db.query(Node).filter(Node.id == job.dest_node_id).first()
            if not source or not dest:
                continue
            try:
                active = await syncoid_service.is_replication_active(
                    executor_host=source.hostname,
                    executor_port=source.ssh_port,
                    executor_user=source.ssh_user,
                    executor_key=source.ssh_key_path,
                    source_dataset=job.source_dataset,
                    dest_host=dest.hostname,
                    dest_port=dest.ssh_port,
                    dest_user=dest.ssh_user,
                    dest_key=dest.ssh_key_path,
                    dest_dataset=job.dest_dataset,
                )
            except Exception:
                active = False
            if active:
                job.last_status = "running"
                if hasattr(job, "current_status"):
                    try:
                        job.current_status = "running"
                    except Exception:
                        pass
                logger.info(
                    f"Reconcile startup: job {job.id} failed in DB ma ancora attivo → running"
                )
        db.commit()
    except Exception as e:
        logger.warning(f"Reconcile sync jobs startup fallito: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()

    await _reconcile_running_sync_jobs_once()
    await reconcile_pending_vm_registrations()


def check_job_access(user: User, job: SyncJob, db: Session) -> bool:
    """Verifica se l'utente ha accesso al job"""
    if user.role == "admin":
        return True
    
    if user.allowed_nodes is None:
        return True
    
    # Deve avere accesso sia al nodo sorgente che destinazione
    return (job.source_node_id in user.allowed_nodes and 
            job.dest_node_id in user.allowed_nodes)


# ============== Endpoints ==============

@router.get("/check-compatibility")
async def check_vm_compatibility(
    source_node_id: int,
    dest_node_id: int,
    vm_id: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verifica compatibilità per replica VM tra sorgente e destinazione.
    Controlla: CPU, bridge di rete, storage ZFS.
    """
    from services.proxmox_service import proxmox_service
    
    source_node = db.query(Node).filter(Node.id == source_node_id).first()
    dest_node = db.query(Node).filter(Node.id == dest_node_id).first()
    
    if not source_node or not dest_node:
        raise HTTPException(status_code=404, detail="Nodi non trovati")
    
    warnings = []
    info = {}
    
    try:
        # 1. Ottieni bridge della VM sorgente
        vm_bridges = await proxmox_service.get_vm_network_bridges(
            hostname=source_node.hostname,
            vmid=vm_id,
            vm_type=vm_type,
            port=source_node.ssh_port,
            username=source_node.ssh_user,
            key_path=source_node.ssh_key_path
        )
        info["source_vm_bridges"] = vm_bridges
        
        # 2. Ottieni bridge disponibili su destinazione
        dest_bridges = await proxmox_service.get_node_bridges(
            hostname=dest_node.hostname,
            port=dest_node.ssh_port,
            username=dest_node.ssh_user,
            key_path=dest_node.ssh_key_path
        )
        info["dest_node_bridges"] = dest_bridges
        
        # 3. Verifica compatibilità bridge
        missing_bridges = [b for b in vm_bridges if b not in dest_bridges]
        if missing_bridges:
            warnings.append({
                "type": "network",
                "level": "warning",
                "message": f"Bridge di rete non presenti su destinazione: {', '.join(missing_bridges)}",
                "details": f"La VM usa: {', '.join(vm_bridges)}. Disponibili su {dest_node.name}: {', '.join(dest_bridges) if dest_bridges else 'nessuno'}"
            })
        
        # 4. Ottieni tipo CPU della VM
        if vm_type == "qemu":
            vm_cpu = await proxmox_service.get_vm_cpu_type(
                hostname=source_node.hostname,
                vmid=vm_id,
                port=source_node.ssh_port,
                username=source_node.ssh_user,
                key_path=source_node.ssh_key_path
            )
            info["source_vm_cpu"] = vm_cpu
            
            # 5. Ottieni info CPU destinazione
            dest_cpu_info = await proxmox_service.get_node_cpu_info(
                hostname=dest_node.hostname,
                port=dest_node.ssh_port,
                username=dest_node.ssh_user,
                key_path=dest_node.ssh_key_path
            )
            info["dest_cpu"] = dest_cpu_info
            
            # 6. Verifica compatibilità CPU
            if vm_cpu and vm_cpu != "host":
                # CPU specifiche che richiedono AVX512
                avx512_cpus = ["x86-64-v4", "Cascadelake", "Icelake", "Sapphire"]
                needs_avx512 = any(cpu in vm_cpu for cpu in avx512_cpus)
                
                if needs_avx512 and not dest_cpu_info.get("supports_avx512"):
                    warnings.append({
                        "type": "cpu",
                        "level": "error",
                        "message": f"CPU '{vm_cpu}' non supportata su destinazione",
                        "details": f"La CPU del nodo {dest_node.name} ({dest_cpu_info.get('model', 'Unknown')}) non supporta AVX-512. Attiva 'Forza CPU host' per risolvere."
                    })
        
        # 7. Verifica storage ZFS replica
        from services.ssh_service import ssh_service
        
        # Controlla se esiste lo storage "replica" su destinazione
        storage_check = await ssh_service.execute(
            hostname=dest_node.hostname,
            command="pvesm status | grep -E '^replica\\s'",
            port=dest_node.ssh_port,
            username=dest_node.ssh_user,
            key_path=dest_node.ssh_key_path
        )
        
        if not storage_check.success or not storage_check.stdout.strip():
            # Verifica se esiste il dataset zfs/replica
            zfs_check = await ssh_service.execute(
                hostname=dest_node.hostname,
                command="zfs list -H -o name | grep -E '^[^/]+/replica$' | head -1",
                port=dest_node.ssh_port,
                username=dest_node.ssh_user,
                key_path=dest_node.ssh_key_path
            )
            
            if zfs_check.success and zfs_check.stdout.strip():
                pool_name = zfs_check.stdout.strip()
                warnings.append({
                    "type": "storage",
                    "level": "info",
                    "message": f"Storage 'replica' non registrato su {dest_node.name}",
                    "details": f"Dataset ZFS '{pool_name}' esiste ma non è registrato come storage Proxmox. Verrà creato automaticamente durante la registrazione VM."
                })
            else:
                # Il dataset non esiste - verrà creato da syncoid
                info["dest_storage_status"] = "will_be_created"
        else:
            info["dest_storage_status"] = "exists"
        
        return {
            "compatible": len([w for w in warnings if w["level"] == "error"]) == 0,
            "warnings": warnings,
            "info": info
        }
        
    except Exception as e:
        logger.error(f"Errore verifica compatibilità: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[SyncJobResponseWithNodes])
async def list_sync_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i job di sincronizzazione"""
    jobs = db.query(SyncJob).all()
    accessible = [j for j in jobs if check_job_access(user, j, db)]
    nodes_by_id = {n.id: n for n in db.query(Node).all()}

    live_by_id: Dict[int, Dict[str, Any]] = {}
    for job in accessible:
        source_node = nodes_by_id.get(job.source_node_id)
        dest_node = nodes_by_id.get(job.dest_node_id)
        if source_node and dest_node:
            live_by_id[job.id] = await _get_sync_job_live_state(job, source_node, dest_node)

    groups: Dict[str, List[SyncJob]] = {}
    for job in accessible:
        if job.vm_group_id:
            groups.setdefault(job.vm_group_id, []).append(job)

    group_progress: Dict[str, Dict[str, Any]] = {}
    for gid, group_jobs in groups.items():
        gp = await _compute_vm_group_progress(group_jobs, live_by_id, nodes_by_id)
        if gp:
            group_progress[gid] = gp

    group_is_running: Dict[str, bool] = {}
    for gid, group_jobs in groups.items():
        gkey = _vm_group_key(gid)
        group_is_running[gid] = scheduler_service.is_running(gkey) or any(
            live_by_id.get(j.id, {}).get("is_replicating")
            or (live_by_id.get(j.id, {}).get("last_status") or "").lower() == "running"
            for j in group_jobs
        )

    result = []
    for job in accessible:
        job_dict = SyncJobResponse.model_validate(job).model_dump()
        source_node = nodes_by_id.get(job.source_node_id)
        dest_node = nodes_by_id.get(job.dest_node_id)
        job_dict["source_node_name"] = source_node.name if source_node else None
        job_dict["dest_node_name"] = dest_node.name if dest_node else None

        live = live_by_id.get(job.id, {})
        job_dict["is_replicating"] = live.get("is_replicating", False)
        job_dict["transfer_progress"] = live.get("transfer_progress")
        job_dict["last_status"] = live.get("last_status", job.last_status)
        job_dict["current_status"] = live.get("current_status", getattr(job, "current_status", None))

        if job.vm_group_id:
            if job.vm_group_id in group_progress:
                gp = group_progress[job.vm_group_id]
                job_dict["group_transfer_progress"] = gp
                job_dict["group_disks_done"] = gp.get("disks_done")
                job_dict["group_disks_total"] = gp.get("disks_total")
            job_dict["group_is_running"] = group_is_running.get(job.vm_group_id, False)

        result.append(SyncJobResponseWithNodes(**job_dict))
    
    return result


@router.post("", response_model=SyncJobResponse)
async def create_sync_job(
    job: SyncJobCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo job di sincronizzazione"""
    
    # Verifica nodi esistenti
    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    
    if not source_node:
        raise HTTPException(status_code=400, detail="Nodo sorgente non trovato")
    if not dest_node:
        raise HTTPException(status_code=400, detail="Nodo destinazione non trovato")
    
    # Verifica accesso ai nodi
    if user.allowed_nodes is not None:
        if job.source_node_id not in user.allowed_nodes:
            raise HTTPException(status_code=403, detail="Accesso negato al nodo sorgente")
        if job.dest_node_id not in user.allowed_nodes:
            raise HTTPException(status_code=403, detail="Accesso negato al nodo destinazione")
    
    # Genera nome automatico se non fornito o vuoto
    job_name = job.name.strip() if job.name else ""
    if not job_name:
        # Estrai nome dataset (ultima parte del path)
        source_ds_name = job.source_dataset.split('/')[-1] if '/' in job.source_dataset else job.source_dataset
        job_name = f"{source_node.name} → {dest_node.name}: {source_ds_name}"
    
    # Crea job con nome (generato o fornito)
    job_dict = job.model_dump()
    job_dict['name'] = job_name
    # Allinea schedule (cron) e schedule_config (JSON struct)
    cron, cfg = _resolve_schedule_pair(job_dict.get('schedule'), job_dict.get('schedule_config'))
    job_dict['schedule'] = cron
    job_dict['schedule_config'] = cfg
    db_job = SyncJob(**job_dict, created_by=user.id)
    db.add(db_job)
    
    log_audit(
        db, user.id, "sync_job_created", "sync_job",
        details=f"Created job: {job_name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(db_job)
    
    # Aggiorna scheduler
    if db_job.schedule:
        scheduler_service.update_job_schedule(
            db_job.id, db_job.schedule, db_job.vm_group_id, db_job.last_run
        )
    
    return db_job


class VMReplicaCreate(BaseModel):
    """Schema per creare replica completa di una VM (ZFS / BTRFS / PVE_NATIVE)"""
    vm_id: int
    vm_type: str = "qemu"
    vm_name: Optional[str] = None
    source_node_id: int
    dest_node_id: int
    # Per ZFS/BTRFS: pool/subfolder; per pve_native ignorati
    dest_pool: Optional[str] = None
    dest_subfolder: str = "replica"
    dest_storage: Optional[str] = None  # Nome storage Proxmox destinazione
    dest_vm_id: Optional[int] = None
    dest_vm_name: Optional[str] = None
    dest_vm_name_suffix: Optional[str] = None
    dest_bridge: Optional[str] = None
    dest_vlan: Optional[int] = None
    force_cpu_host: bool = True
    schedule: Optional[str] = None
    schedule_config: Optional[Dict[str, Any]] = None
    compress: str = "lz4"
    recursive: bool = False
    register_vm: bool = True
    keep_snapshots: int = 0  # 0 = solo ultima, N = mantieni ultime N snapshot
    disks: List[dict] = []  # Lista dischi da replicare (se vuota, replica tutti)
    # pve_native specific
    dump_dir: Optional[str] = None
    bandwidth_limit_kb: Optional[int] = None
    pve_compress: Optional[str] = None
    cleanup_after: Optional[bool] = None
    replace_existing: Optional[bool] = None
    
    # BTRFS options
    sync_method: str = "syncoid"  # syncoid | btrfs_send
    btrfs_mount: Optional[str] = None  # Mount point BTRFS sorgente
    btrfs_snapshot_dir: Optional[str] = None  # Directory snapshot sorgente
    btrfs_dest_snapshot_dir: Optional[str] = None  # Directory snapshot destinazione
    btrfs_max_snapshots: int = 5


@router.post("/vm-replica")
async def create_vm_replica_jobs(
    vm_data: VMReplicaCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Crea job di replica per tutti i dischi di una VM.
    Ritorna la lista dei job creati.
    """
    import uuid
    from services.proxmox_service import proxmox_service
    
    # Verifica nodi
    source_node = db.query(Node).filter(Node.id == vm_data.source_node_id).first()
    dest_node = db.query(Node).filter(Node.id == vm_data.dest_node_id).first()
    
    if not source_node:
        raise HTTPException(status_code=400, detail="Nodo sorgente non trovato")
    if not dest_node:
        raise HTTPException(status_code=400, detail="Nodo destinazione non trovato")
    
    # Verifica accesso
    if user.allowed_nodes is not None:
        if vm_data.source_node_id not in user.allowed_nodes:
            raise HTTPException(status_code=403, detail="Accesso negato al nodo sorgente")
        if vm_data.dest_node_id not in user.allowed_nodes:
            raise HTTPException(status_code=403, detail="Accesso negato al nodo destinazione")
    
    # Ottieni i dischi della VM se non specificati
    if not vm_data.disks:
        disks = await proxmox_service.get_vm_disks_with_size(
            hostname=source_node.hostname,
            vmid=vm_data.vm_id,
            vm_type=vm_data.vm_type,
            port=source_node.ssh_port,
            username=source_node.ssh_user,
            key_path=source_node.ssh_key_path
        )
    else:
        disks = vm_data.disks
    
    if not disks:
        raise HTTPException(status_code=400, detail="Nessun disco trovato per questa VM")
    
    # Genera un group_id univoco per tutti i job di questa VM
    vm_group_id = str(uuid.uuid4())[:8]
    
    # Determina VMID destinazione
    dest_vmid = vm_data.dest_vm_id if vm_data.dest_vm_id else vm_data.vm_id
    
    created_jobs = []
    total_size = 0

    # Validazione difensiva: dest_pool / dest_subfolder / dest_storage
    # finiscono nei comandi syncoid via SSH. Solo identifier ZFS-safe.
    _ZFS_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./\-]*$")
    if vm_data.dest_pool and not _ZFS_PART.match(vm_data.dest_pool):
        raise HTTPException(status_code=400, detail=f"dest_pool non valido: {vm_data.dest_pool!r}")
    if vm_data.dest_subfolder and not _ZFS_PART.match(vm_data.dest_subfolder):
        raise HTTPException(status_code=400, detail=f"dest_subfolder non valido: {vm_data.dest_subfolder!r}")
    if vm_data.dest_storage and not _ZFS_PART.match(vm_data.dest_storage):
        raise HTTPException(status_code=400, detail=f"dest_storage non valido: {vm_data.dest_storage!r}")
    if vm_data.dest_vm_name_suffix and not re.fullmatch(r"[A-Za-z0-9_\-]{1,50}", vm_data.dest_vm_name_suffix):
        raise HTTPException(status_code=400, detail=f"dest_vm_name_suffix non valido")
    if vm_data.dest_bridge and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,49}", vm_data.dest_bridge):
        raise HTTPException(status_code=400, detail=f"dest_bridge non valido: {vm_data.dest_bridge!r}")
    if vm_data.dest_vlan is not None and not (1 <= vm_data.dest_vlan <= 4094):
        raise HTTPException(status_code=400, detail=f"dest_vlan fuori range (1-4094): {vm_data.dest_vlan}")
    if vm_data.dest_vm_name and not re.fullmatch(r"[A-Za-z0-9.\-_ ]{1,100}", vm_data.dest_vm_name):
        raise HTTPException(status_code=400, detail=f"dest_vm_name non valido")

    # Allinea lo schedule UNA volta sola: tutti i job della VM condividono
    # la stessa pianificazione.
    _vm_cron, _vm_cfg = _resolve_schedule_pair(vm_data.schedule, vm_data.schedule_config)

    # Path PVE_NATIVE: un solo SyncJob per VM (vzdump dumpa l'intera VM
    # in un colpo, no per-disco). I campi ZFS-specifici sono placeholder.
    if vm_data.sync_method == SyncMethod.PVE_NATIVE.value:
        if vm_data.pve_compress and vm_data.pve_compress not in ("none", "lzo", "gzip", "zstd"):
            raise HTTPException(status_code=400, detail=f"pve_compress non valido: {vm_data.pve_compress!r}")
        if vm_data.dump_dir and not re.fullmatch(r"^/[A-Za-z0-9_./\-]+$", vm_data.dump_dir):
            raise HTTPException(status_code=400, detail=f"dump_dir non valido: {vm_data.dump_dir!r}")
        if vm_data.bandwidth_limit_kb is not None and not (0 <= vm_data.bandwidth_limit_kb <= 10_000_000):
            raise HTTPException(status_code=400, detail=f"bandwidth_limit_kb fuori range")

        job_name = f"VM-{vm_data.vm_id} (pve_native) → {dest_node.name}"
        marker = f"vm:{vm_data.vm_id}"  # placeholder per i campi ZFS-specifici
        db_job = SyncJob(
            name=job_name,
            sync_method=SyncMethod.PVE_NATIVE.value,
            source_node_id=vm_data.source_node_id,
            source_dataset=marker,
            dest_node_id=vm_data.dest_node_id,
            dest_dataset=marker,
            recursive=False,
            compress="zstd",
            schedule=_vm_cron,
            schedule_config=_vm_cfg,
            register_vm=vm_data.register_vm,
            vm_id=vm_data.vm_id,
            dest_vm_id=dest_vmid if dest_vmid != vm_data.vm_id else None,
            vm_type=vm_data.vm_type,
            vm_name=vm_data.vm_name,
            dest_vm_name=vm_data.dest_vm_name,
            dest_vm_name_suffix=vm_data.dest_vm_name_suffix,
            dest_bridge=vm_data.dest_bridge,
            dest_vlan=vm_data.dest_vlan,
            force_cpu_host=vm_data.force_cpu_host,
            keep_snapshots=0,
            vm_group_id=vm_group_id,
            disk_name=None,
            source_storage=None,
            dest_storage=vm_data.dest_storage,
            dest_subfolder=None,
            # pve_native parametri
            dump_dir=vm_data.dump_dir,
            bandwidth_limit_kb=vm_data.bandwidth_limit_kb,
            pve_compress=vm_data.pve_compress or "zstd",
            cleanup_after=vm_data.cleanup_after if vm_data.cleanup_after is not None else True,
            replace_existing=bool(vm_data.replace_existing),
            created_by=user.id,
            is_active=True,
        )
        db.add(db_job)
        log_audit(
            db, user.id, "vm_replica_pve_native_created", "sync_job",
            details=f"VM {vm_data.vm_id} -> {dest_node.name} (pve_native)",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(db_job)
        if _vm_cron:
            scheduler_service.update_job_schedule(
                db_job.id, _vm_cron, vm_group_id, db_job.last_run
            )
        return {
            "vm_group_id": vm_group_id,
            "vm_id": vm_data.vm_id,
            "vm_name": vm_data.vm_name,
            "total_jobs": 1,
            "method": "pve_native",
            "jobs": [{"id": db_job.id, "name": job_name}],
        }

    for disk in disks:
        if not disk.get("dataset"):
            continue
        
        # Costruisci il path destinazione
        # Es: dest_pool/replica/vm-100-disk-0
        source_dataset = disk["dataset"]
        dataset_name = source_dataset.split("/")[-1]  # es: vm-100-disk-0
        
        if vm_data.dest_subfolder:
            dest_dataset = f"{vm_data.dest_pool}/{vm_data.dest_subfolder}/{dataset_name}"
        else:
            dest_dataset = f"{vm_data.dest_pool}/{dataset_name}"
        
        # Nome job: VM-100 scsi0 -> Node2
        job_name = f"VM-{vm_data.vm_id} {disk.get('disk_name', 'disk')} → {dest_node.name}"
        
        # Crea il job
        # Determina storage sorgente (dal disco) e destinazione
        source_storage = disk.get("storage", None)  # es: local-zfs
        dest_zfs_path = (
            f"{vm_data.dest_pool}/{vm_data.dest_subfolder}"
            if vm_data.dest_subfolder
            else vm_data.dest_pool
        )
        base_storage = vm_data.dest_storage or vm_data.dest_pool
        from services.proxmox_service import proxmox_service as _px
        dest_storage = _px.derive_zfs_storage_name(base_storage, dest_zfs_path)
        
        db_job = SyncJob(
            name=job_name,
            sync_method=vm_data.sync_method,
            source_node_id=vm_data.source_node_id,
            source_dataset=source_dataset,
            dest_node_id=vm_data.dest_node_id,
            dest_dataset=dest_dataset,
            recursive=vm_data.recursive,
            compress=vm_data.compress,
            schedule=_vm_cron,
            schedule_config=_vm_cfg,
            register_vm=vm_data.register_vm,
            vm_id=vm_data.vm_id,
            dest_vm_id=dest_vmid if dest_vmid != vm_data.vm_id else None,
            vm_type=vm_data.vm_type,
            vm_name=vm_data.vm_name,
            dest_vm_name=vm_data.dest_vm_name,
            dest_vm_name_suffix=vm_data.dest_vm_name_suffix,
            dest_bridge=vm_data.dest_bridge,
            dest_vlan=vm_data.dest_vlan,
            force_cpu_host=vm_data.force_cpu_host,
            keep_snapshots=vm_data.keep_snapshots,
            vm_group_id=vm_group_id,
            disk_name=disk.get("disk_name"),
            source_storage=source_storage,
            dest_storage=dest_storage,
            dest_subfolder=vm_data.dest_subfolder,
            # BTRFS options
            btrfs_snapshot_dir=vm_data.btrfs_snapshot_dir,
            btrfs_dest_snapshot_dir=vm_data.btrfs_dest_snapshot_dir,
            btrfs_max_snapshots=vm_data.btrfs_max_snapshots,
            created_by=user.id,
            is_active=True
        )
        
        db.add(db_job)
        total_size += disk.get("size_bytes", 0)
        
        created_jobs.append({
            "disk_name": disk.get("disk_name"),
            "source_dataset": source_dataset,
            "dest_dataset": dest_dataset,
            "size": disk.get("size", "N/A")
        })
    
    db.commit()
    
    # Log audit
    log_audit(
        db, user.id, "vm_replica_created", "sync_job",
        details=f"Created {len(created_jobs)} jobs for VM {vm_data.vm_id} (group: {vm_group_id})",
        ip_address=request.client.host if request.client else None
    )
    
    # Aggiorna scheduler per il gruppo VM (una sola chiave vmgroup_)
    if vm_data.schedule:
        scheduler_service.update_vm_group_schedule(
            vm_group_id, vm_data.schedule
        )
    
    return {
        "success": True,
        "vm_id": vm_data.vm_id,
        "vm_group_id": vm_group_id,
        "dest_vm_id": dest_vmid,
        "jobs_created": len(created_jobs),
        "total_size": proxmox_service._format_size(total_size),
        "jobs": created_jobs
    }


@router.get("/vm-group/{vm_group_id}")
async def get_vm_group_jobs(
    vm_group_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene tutti i job di un gruppo VM"""
    jobs = db.query(SyncJob).filter(SyncJob.vm_group_id == vm_group_id).all()
    
    if not jobs:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    
    # Verifica accesso al primo job
    if not check_job_access(user, jobs[0], db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    return {
        "vm_group_id": vm_group_id,
        "vm_id": jobs[0].vm_id,
        "vm_name": jobs[0].vm_name,
        "total_jobs": len(jobs),
        "jobs": [SyncJobResponseWithNodes(
            **j.__dict__,
            source_node_name=j.source_node.name if j.source_node else None,
            dest_node_name=j.dest_node.name if j.dest_node else None
        ) for j in jobs]
    }


@router.post("/vm-group/{vm_group_id}/run")
async def run_vm_group_jobs(
    vm_group_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue in sequenza tutti i dischi del gruppo VM (replica completa del gruppo)."""
    jobs = db.query(SyncJob).filter(SyncJob.vm_group_id == vm_group_id).all()

    if not jobs:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")

    active_jobs = [j for j in jobs if check_job_access(user, j, db) and j.is_active]
    if not active_jobs:
        raise HTTPException(status_code=403, detail="Nessun job accessibile nel gruppo")

    group_key = _vm_group_key(vm_group_id)
    if not scheduler_service.mark_running(group_key):
        raise HTTPException(status_code=409, detail="Replica VM già in esecuzione")

    background_tasks.add_task(
        _run_vm_group_background, vm_group_id, group_key, user.id, True
    )

    log_audit(
        db, user.id, "vm_group_started", "sync_job",
        details=f"Sequential run group {vm_group_id} ({len(active_jobs)} dischi)",
        ip_address=request.client.host if request.client else None,
    )

    return {
        "success": True,
        "vm_group_id": vm_group_id,
        "mode": "sequential",
        "disks_total": len(active_jobs),
        "message": f"Replica sequenziale avviata ({len(active_jobs)} dischi)",
    }


@router.delete("/vm-group/{vm_group_id}")
async def delete_vm_group_jobs(
    vm_group_id: str,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina tutti i job di un gruppo VM"""
    jobs = db.query(SyncJob).filter(SyncJob.vm_group_id == vm_group_id).all()
    
    if not jobs:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    
    deleted = 0
    scheduler_service.remove_vm_group_schedule(vm_group_id)
    for job in jobs:
        if check_job_access(user, job, db):
            scheduler_service.remove_job(job.id, job.vm_group_id)
            db.delete(job)
            deleted += 1
    
    db.commit()
    
    log_audit(
        db, user.id, "vm_group_deleted", "sync_job",
        details=f"Deleted {deleted} jobs from group {vm_group_id}",
        ip_address=request.client.host if request.client else None
    )
    
    return {"success": True, "jobs_deleted": deleted}


@router.get("/stats/summary")
async def get_sync_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene statistiche sui job di sincronizzazione"""
    from datetime import timedelta

    total_jobs = db.query(SyncJob).count()
    active_jobs = db.query(SyncJob).filter(SyncJob.is_active == True).count()

    yesterday = datetime.utcnow() - timedelta(days=1)

    recent_logs = db.query(JobLog).filter(
        JobLog.job_type == "sync",
        JobLog.started_at >= yesterday
    ).all()

    success_count = len([l for l in recent_logs if l.status == "success"])
    failed_count = len([l for l in recent_logs if l.status == "failed"])

    return {
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "runs_24h": len(recent_logs),
        "success_24h": success_count,
        "failed_24h": failed_count,
        "success_rate": round(success_count / len(recent_logs) * 100, 1) if recent_logs else 0
    }


@router.get("/{job_id}", response_model=SyncJobResponseWithNodes)
async def get_sync_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene un job specifico"""
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    job_dict = SyncJobResponse.model_validate(job).model_dump()
    
    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    
    job_dict["source_node_name"] = source_node.name if source_node else None
    job_dict["dest_node_name"] = dest_node.name if dest_node else None
    
    return SyncJobResponseWithNodes(**job_dict)


@router.put("/{job_id}", response_model=SyncJobResponse)
async def update_sync_job(
    job_id: int,
    update: SyncJobUpdate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Aggiorna un job di replica.
    
    Permette di modificare tutti i parametri inclusi:
    - Nodi sorgente/destinazione
    - Dataset
    - Schedule
    - Opzioni di compressione e sincronizzazione
    - Configurazione VM
    """
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    update_data = update.model_dump(exclude_unset=True)
    changes = []
    
    # Valida e verifica accesso ai nuovi nodi se cambiati
    if "source_node_id" in update_data and update_data["source_node_id"] != job.source_node_id:
        new_source = db.query(Node).filter(Node.id == update_data["source_node_id"]).first()
        if not new_source:
            raise HTTPException(status_code=400, detail="Nuovo nodo sorgente non trovato")
        if user.allowed_nodes is not None and update_data["source_node_id"] not in user.allowed_nodes:
            raise HTTPException(status_code=403, detail="Accesso negato al nuovo nodo sorgente")
        changes.append(f"source_node: {job.source_node_id} -> {update_data['source_node_id']}")
    
    if "dest_node_id" in update_data and update_data["dest_node_id"] != job.dest_node_id:
        new_dest = db.query(Node).filter(Node.id == update_data["dest_node_id"]).first()
        if not new_dest:
            raise HTTPException(status_code=400, detail="Nuovo nodo destinazione non trovato")
        if user.allowed_nodes is not None and update_data["dest_node_id"] not in user.allowed_nodes:
            raise HTTPException(status_code=403, detail="Accesso negato al nuovo nodo destinazione")
        changes.append(f"dest_node: {job.dest_node_id} -> {update_data['dest_node_id']}")
    
    # Traccia altre modifiche importanti
    if "schedule" in update_data and update_data["schedule"] != job.schedule:
        changes.append(f"schedule: '{job.schedule}' -> '{update_data['schedule']}'")
    if "is_active" in update_data and update_data["is_active"] != job.is_active:
        changes.append(f"is_active: {job.is_active} -> {update_data['is_active']}")
    if "source_dataset" in update_data and update_data["source_dataset"] != job.source_dataset:
        changes.append(f"source_dataset changed")
    if "dest_dataset" in update_data and update_data["dest_dataset"] != job.dest_dataset:
        changes.append(f"dest_dataset changed")
    
    # Riallinea schedule/schedule_config se uno dei due è cambiato
    if "schedule" in update_data or "schedule_config" in update_data:
        new_cron, new_cfg = _resolve_schedule_pair(
            update_data.get("schedule", job.schedule),
            update_data.get("schedule_config", job.schedule_config),
        )
        update_data["schedule"] = new_cron
        update_data["schedule_config"] = new_cfg

    # Applica gli aggiornamenti
    for key, value in update_data.items():
        setattr(job, key, value)

    log_audit(
        db, user.id, "sync_job_updated", "sync_job",
        resource_id=job_id,
        details=f"Updated job '{job.name}': {', '.join(changes) if changes else 'minor changes'}",
        ip_address=request.client.host if request.client else None
    )

    db.commit()
    db.refresh(job)

    # Aggiorna scheduler
    if job.is_active and job.schedule:
        scheduler_service.update_job_schedule(
            job.id, job.schedule, job.vm_group_id, job.last_run
        )
    else:
        scheduler_service.remove_job(job.id, job.vm_group_id)
        if job.vm_group_id:
            siblings_active = db.query(SyncJob).filter(
                SyncJob.vm_group_id == job.vm_group_id,
                SyncJob.id != job.id,
                SyncJob.is_active == True,  # noqa: E712
                SyncJob.schedule.isnot(None),
                SyncJob.schedule != "",
            ).count()
            if siblings_active == 0:
                scheduler_service.remove_vm_group_schedule(job.vm_group_id)

    return job


@router.delete("/{job_id}")
async def delete_sync_job(
    job_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina un job"""
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    job_name = job.name
    vm_group_id = job.vm_group_id
    scheduler_service.remove_job(job_id, vm_group_id)
    
    db.delete(job)
    db.flush()
    
    if vm_group_id:
        remaining = db.query(SyncJob).filter(SyncJob.vm_group_id == vm_group_id).count()
        if remaining == 0:
            scheduler_service.remove_vm_group_schedule(vm_group_id)
    
    log_audit(
        db, user.id, "sync_job_deleted", "sync_job",
        resource_id=job_id,
        details=f"Deleted job: {job_name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    return {"message": "Job eliminato"}


@router.post("/{job_id}/run")
async def run_sync_job(
    job_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue un job manualmente"""
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")

    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")

    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()

    if not source_node or not dest_node:
        raise HTTPException(status_code=400, detail="Nodi non configurati correttamente")

    if job.vm_group_id:
        group_key = _vm_group_key(job.vm_group_id)
        if not scheduler_service.mark_running(group_key):
            raise HTTPException(status_code=409, detail="Replica VM già in esecuzione")
        background_tasks.add_task(
            _run_vm_group_background, job.vm_group_id, group_key, user.id, True
        )
        log_audit(
            db, user.id, "sync_job_started", "sync_job",
            resource_id=job_id,
            details=f"Manual run VM group {job.vm_group_id} (da job {job.name})",
            ip_address=request.client.host if request.client else None,
        )
        return {
            "message": "Replica sequenziale di tutti i dischi avviata",
            "vm_group_id": job.vm_group_id,
            "mode": "sequential",
        }

    # No double-fire: se lo scheduler ha gia' marcato il job come running,
    # rifiuta la run manuale (l'utente vedra' il progress in UI).
    job_key = f"sync_{job_id}"
    if not scheduler_service.mark_running(job_key):
        raise HTTPException(status_code=409, detail="Job già in esecuzione")

    background_tasks.add_task(_run_sync_job_background, job_id, job_key, user.id)
    
    log_audit(
        db, user.id, "sync_job_started", "sync_job",
        resource_id=job_id,
        details=f"Manual run: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    return {"message": "Job avviato in background", "job_id": job_id}


@router.get("/{job_id}/logs")
async def get_job_logs(
    job_id: int,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene i log di un job"""
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")

    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")

    logs = db.query(JobLog).filter(
        JobLog.job_id == job_id
    ).order_by(JobLog.started_at.desc()).limit(limit).all()

    return logs


@router.get("/{job_id}/progress")
async def get_job_progress(
    job_id: int,
    tail: int = 200,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stato live del job + ultime righe di output del log piu' recente.

    Polling-friendly (nessun WebSocket): la UI puo' chiamarlo ogni 1-2s
    durante l'esecuzione. Risposta:
      {
        is_running: bool,            # secondo lo scheduler in-memory
        current_status: str | null,
        last_status: str | null,
        last_run: iso str | null,
        last_duration: int | null,
        last_transferred: str | null,
        run_count: int,
        error_count: int,
        log: {
          id: int,
          status: str,
          started_at: iso,
          completed_at: iso | null,
          message: str,
          output_tail: [str, ...]    # ultime `tail` righe di stdout
        } | null
      }
    """
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")

    last_log = (
        db.query(JobLog)
        .filter(JobLog.job_id == job_id)
        .order_by(JobLog.started_at.desc())
        .first()
    )

    log_payload = None
    if last_log:
        output_full = (last_log.output or "")
        # tail logico: ultime N righe, niente HTML/ANSI ripuliamo solo
        # \r in eccesso (progress bar di syncoid).
        cleaned = output_full.replace("\r", "\n")
        lines = [l for l in cleaned.split("\n") if l.strip()]
        if tail > 0:
            lines = lines[-tail:]
        log_payload = {
            "id": last_log.id,
            "status": last_log.status,
            "started_at": last_log.started_at.isoformat() if last_log.started_at else None,
            "completed_at": last_log.completed_at.isoformat() if last_log.completed_at else None,
            "message": last_log.message,
            "duration": last_log.duration,
            "transferred": last_log.transferred,
            "error": last_log.error,
            "output_tail": lines,
        }

    job_key = f"sync_{job_id}"
    in_mem_running = scheduler_service.is_running(job_key)
    db_running = (job.last_status or "").lower() == "running"
    log_running = bool(
        last_log
        and (last_log.status or "").lower() in ("started", "running")
        and not last_log.completed_at
    )
    is_running = in_mem_running or db_running or log_running

    sync_method = job.sync_method or SyncMethod.SYNCOID.value
    if not is_running and sync_method not in (
        SyncMethod.BTRFS_SEND.value,
        SyncMethod.PVE_NATIVE.value,
    ):
        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
        if source_node and dest_node:
            try:
                remote_active = await syncoid_service.is_replication_active(
                    executor_host=source_node.hostname,
                    executor_port=source_node.ssh_port,
                    executor_user=source_node.ssh_user,
                    executor_key=source_node.ssh_key_path,
                    source_dataset=job.source_dataset,
                    dest_host=dest_node.hostname,
                    dest_port=dest_node.ssh_port,
                    dest_user=dest_node.ssh_user,
                    dest_key=dest_node.ssh_key_path,
                    dest_dataset=job.dest_dataset,
                )
                if remote_active:
                    is_running = True
                    if (job.last_status or "").lower() != "running":
                        job.last_status = "running"
                        if hasattr(job, "current_status"):
                            try:
                                job.current_status = "running"
                            except Exception:
                                pass
                        db.commit()
            except Exception as e:
                logger.debug(f"remote active check job {job_id}: {e}")

    transfer_progress = None
    if is_running and sync_method not in (
        SyncMethod.BTRFS_SEND.value,
        SyncMethod.PVE_NATIVE.value,
    ):
        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
        if source_node and dest_node:
            try:
                transfer_progress = await syncoid_service.get_replication_progress(
                    executor_host=source_node.hostname,
                    executor_port=source_node.ssh_port,
                    executor_user=source_node.ssh_user,
                    executor_key=source_node.ssh_key_path,
                    source_dataset=job.source_dataset,
                    dest_host=dest_node.hostname,
                    dest_port=dest_node.ssh_port,
                    dest_user=dest_node.ssh_user,
                    dest_key=dest_node.ssh_key_path,
                    dest_dataset=job.dest_dataset,
                )
            except Exception as e:
                logger.debug(f"transfer_progress job {job_id}: {e}")

    eff_last = "running" if is_running else job.last_status
    eff_current = "running" if is_running else getattr(job, "current_status", None)

    return {
        "id": job.id,
        "name": job.name,
        "is_running": is_running,
        "current_status": eff_current,
        "last_status": eff_last,
        "last_run": job.last_run.isoformat() if job.last_run else None,
        "last_duration": getattr(job, "last_duration", None),
        "last_transferred": getattr(job, "last_transferred", None),
        "run_count": getattr(job, "run_count", 0),
        "error_count": getattr(job, "error_count", 0),
        "transfer_progress": transfer_progress,
        "log": log_payload,
    }


@router.post("/{job_id}/toggle")
async def toggle_sync_job(
    job_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Attiva/disattiva un job"""
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    job.is_active = not job.is_active
    
    log_audit(
        db, user.id, "sync_job_toggled", "sync_job",
        resource_id=job_id,
        details=f"{'Enabled' if job.is_active else 'Disabled'}: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    
    if job.is_active and job.schedule:
        scheduler_service.update_job_schedule(
            job.id, job.schedule, job.vm_group_id, job.last_run
        )
    else:
        scheduler_service.remove_job(job.id, job.vm_group_id)
        if job.vm_group_id:
            siblings_active = db.query(SyncJob).filter(
                SyncJob.vm_group_id == job.vm_group_id,
                SyncJob.id != job.id,
                SyncJob.is_active == True,  # noqa: E712
                SyncJob.schedule.isnot(None),
                SyncJob.schedule != "",
            ).count()
            if siblings_active == 0:
                scheduler_service.remove_vm_group_schedule(job.vm_group_id)
    
    return {"is_active": job.is_active}


@router.post("/{job_id}/register-vm")
async def register_vm_manually(
    job_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Registra manualmente la VM associata a un job sul nodo destinazione.
    Copia la configurazione dalla sorgente e registra la VM.
    """
    from services.ssh_service import ssh_service
    from services.proxmox_service import proxmox_service
    
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    if not job.vm_id:
        raise HTTPException(status_code=400, detail="VMID sorgente non configurato per questo job")
    
    # Usa dest_vm_id se specificato, altrimenti usa vm_id
    target_vmid = job.dest_vm_id if job.dest_vm_id else job.vm_id
    
    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    
    if not source_node or not dest_node:
        raise HTTPException(status_code=400, detail="Nodi non configurati")
    
    vm_type = job.vm_type or "qemu"
    
    # Ottieni la configurazione dalla sorgente
    if vm_type == "qemu":
        config_path = f"/etc/pve/qemu-server/{job.vm_id}.conf"
    else:
        config_path = f"/etc/pve/lxc/{job.vm_id}.conf"
    
    config_result = await ssh_service.execute(
        hostname=source_node.hostname,
        command=f"cat {config_path} 2>/dev/null",
        port=source_node.ssh_port,
        username=source_node.ssh_user,
        key_path=source_node.ssh_key_path,
        timeout=30
    )
    
    if not config_result.success or not config_result.stdout.strip():
        raise HTTPException(
            status_code=400, 
            detail=f"Configurazione VM {job.vm_id} non trovata su {source_node.name}. "
                   f"Path: {config_path}, Errore: {config_result.stderr}"
        )
    
    # Modifica la configurazione
    config_content = config_result.stdout
    
    # Sostituisci i path del dataset
    # Proxmox usa il formato pool:dataset (con : invece di /)
    source_zfs = job.source_dataset.split("/")[0]  # pool sorgente
    dest_zfs = job.dest_dataset.split("/")[0]  # pool destinazione
    
    # Determina il pool ZFS destinazione per creare lo storage
    dest_zfs_pool = "/".join(job.dest_dataset.split("/")[:-1])  # es: ZFS/replica
    if not dest_zfs_pool:
        dest_zfs_pool = job.dest_dataset.split("/")[0]
    
    # Ottieni i bridge disponibili sulla destinazione per il warning
    dest_bridges = await proxmox_service.get_node_bridges(
        hostname=dest_node.hostname,
        port=dest_node.ssh_port,
        username=dest_node.ssh_user,
        key_path=dest_node.ssh_key_path
    )
    
    # Registra la VM sulla destinazione con ID diverso se specificato
    # Passa source_storage e dest_storage per la sostituzione automatica
    force_cpu = getattr(job, 'force_cpu_host', True)  # Default True per compatibilità
    success, msg, warnings = await proxmox_service.register_vm(
        hostname=dest_node.hostname,
        vmid=target_vmid,
        vm_type=vm_type,
        config_content=config_content,
        source_storage=job.source_storage,
        dest_storage=job.dest_storage,
        dest_zfs_pool=dest_zfs_pool,
        vm_name_suffix=job.dest_vm_name_suffix,
        new_name=getattr(job, "dest_vm_name", None),
        force_cpu_host=force_cpu,
        dest_node_bridges=dest_bridges,
        dest_bridge=getattr(job, "dest_bridge", None),
        dest_vlan=getattr(job, "dest_vlan", None),
        port=dest_node.ssh_port,
        username=dest_node.ssh_user,
        key_path=dest_node.ssh_key_path
    )
    
    if success:
        log_audit(
            db, user.id, "vm_registered", "sync_job",
            resource_id=job_id,
            details=f"VM {target_vmid} registrata su {dest_node.name}" + (f" (da VM {job.vm_id})" if target_vmid != job.vm_id else ""),
            ip_address=request.client.host if request.client else None
        )
        
        response = {
            "success": True,
            "message": f"VM {target_vmid} ({vm_type}) registrata su {dest_node.name}" + (f" (copiata da VM {job.vm_id})" if target_vmid != job.vm_id else ""),
            "config_path": config_path,
            "source_vmid": job.vm_id,
            "dest_vmid": target_vmid
        }
        
        # Aggiungi warnings se presenti
        if warnings:
            response["warnings"] = warnings
            response["message"] += f"\n⚠️ {len(warnings)} avvisi: " + "; ".join(w for w in warnings)
        
        return response
    else:
        raise HTTPException(status_code=500, detail=f"Registrazione fallita: {msg}")


# ============== Snapshot Management ==============

class SnapshotInfo(BaseModel):
    """Info su una snapshot"""
    name: str  # Nome completo (dataset@snapshot)
    snapshot_name: str  # Solo nome snapshot
    creation: datetime
    used: Optional[str] = None  # Spazio usato
    referenced: Optional[str] = None  # Spazio referenziato


@router.get("/{job_id}/snapshots", response_model=List[SnapshotInfo])
async def list_job_snapshots(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lista le snapshot disponibili sul dataset destinazione di un job.
    Utile per vedere le versioni disponibili per il recovery.
    """
    from services.ssh_service import ssh_service
    
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    if not dest_node:
        raise HTTPException(status_code=404, detail="Nodo destinazione non trovato")
    
    # Lista snapshot sul dataset destinazione (syncoid_, autosnap_, backup_, retention_)
    cmd = f"zfs list -t snapshot -o name,creation,used,referenced -s creation -H {job.dest_dataset} 2>/dev/null | grep -E 'syncoid_|autosnap_|backup_|retention_' || true"
    
    result = await ssh_service.execute(
        hostname=dest_node.hostname,
        command=cmd,
        port=dest_node.ssh_port,
        username=dest_node.ssh_user,
        key_path=dest_node.ssh_key_path,
        timeout=60
    )
    
    snapshots = []
    if result.success and result.stdout.strip():
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) >= 2:
                full_name = parts[0].strip()
                if '@' in full_name:
                    snap_name = full_name.split('@')[1]
                    # Parse creation date (format: Mon Dec  8 10:30 2025)
                    try:
                        from dateutil import parser
                        creation_str = parts[1].strip() if len(parts) > 1 else ""
                        creation = parser.parse(creation_str) if creation_str else datetime.utcnow()
                    except:
                        creation = datetime.utcnow()
                    
                    snapshots.append(SnapshotInfo(
                        name=full_name,
                        snapshot_name=snap_name,
                        creation=creation,
                        used=parts[2].strip() if len(parts) > 2 else None,
                        referenced=parts[3].strip() if len(parts) > 3 else None
                    ))
    
    # Ordina per data decrescente (più recente prima)
    snapshots.sort(key=lambda x: x.creation, reverse=True)
    
    return snapshots


@router.post("/{job_id}/snapshots/{snapshot_name}/rollback")
async def rollback_to_snapshot(
    job_id: int,
    snapshot_name: str,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Esegue rollback del dataset destinazione a una snapshot specifica.
    ATTENZIONE: Questo elimina tutti i dati successivi alla snapshot!
    """
    from services.ssh_service import ssh_service
    
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    if not dest_node:
        raise HTTPException(status_code=404, detail="Nodo destinazione non trovato")
    
    # Verifica che la snapshot esista
    full_snapshot = f"{job.dest_dataset}@{snapshot_name}"
    check_cmd = f"zfs list -t snapshot {full_snapshot} 2>/dev/null && echo 'EXISTS'"
    
    check_result = await ssh_service.execute(
        hostname=dest_node.hostname,
        command=check_cmd,
        port=dest_node.ssh_port,
        username=dest_node.ssh_user,
        key_path=dest_node.ssh_key_path,
        timeout=30
    )
    
    if "EXISTS" not in check_result.stdout:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_name} non trovata")
    
    # Esegui rollback (con -r per eliminare snapshot più recenti)
    rollback_cmd = f"zfs rollback -r {full_snapshot}"
    
    result = await ssh_service.execute(
        hostname=dest_node.hostname,
        command=rollback_cmd,
        port=dest_node.ssh_port,
        username=dest_node.ssh_user,
        key_path=dest_node.ssh_key_path,
        timeout=300
    )
    
    if result.success:
        log_audit(
            db, user.id, "snapshot_rollback", "sync_job",
            resource_id=job_id,
            details=f"Rollback a {snapshot_name} su {dest_node.name}:{job.dest_dataset}",
            ip_address=request.client.host if request.client else None
        )
        return {
            "success": True,
            "message": f"Rollback completato a {snapshot_name}",
            "snapshot": full_snapshot
        }
    else:
        raise HTTPException(
            status_code=500, 
            detail=f"Errore rollback: {result.stderr or result.stdout}"
        )


@router.post("/{job_id}/snapshots/{snapshot_name}/clone")
async def clone_snapshot(
    job_id: int,
    snapshot_name: str,
    clone_name: str,  # Query param per il nome del clone
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Clona una snapshot in un nuovo dataset.
    Utile per recuperare dati senza modificare il dataset originale.
    """
    from services.ssh_service import ssh_service
    
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    if not dest_node:
        raise HTTPException(status_code=404, detail="Nodo destinazione non trovato")
    
    # Costruisci path del clone (stesso pool del dataset originale)
    pool = job.dest_dataset.split('/')[0]
    clone_dataset = f"{pool}/{clone_name}"
    full_snapshot = f"{job.dest_dataset}@{snapshot_name}"
    
    # Verifica che il clone non esista già
    check_cmd = f"zfs list {clone_dataset} 2>/dev/null && echo 'EXISTS'"
    check_result = await ssh_service.execute(
        hostname=dest_node.hostname,
        command=check_cmd,
        port=dest_node.ssh_port,
        username=dest_node.ssh_user,
        key_path=dest_node.ssh_key_path,
        timeout=30
    )
    
    if "EXISTS" in check_result.stdout:
        raise HTTPException(status_code=400, detail=f"Dataset {clone_dataset} esiste già")
    
    # Crea clone
    clone_cmd = f"zfs clone {full_snapshot} {clone_dataset}"
    
    result = await ssh_service.execute(
        hostname=dest_node.hostname,
        command=clone_cmd,
        port=dest_node.ssh_port,
        username=dest_node.ssh_user,
        key_path=dest_node.ssh_key_path,
        timeout=120
    )
    
    if result.success:
        log_audit(
            db, user.id, "snapshot_clone", "sync_job",
            resource_id=job_id,
            details=f"Clonata {snapshot_name} in {clone_dataset} su {dest_node.name}",
            ip_address=request.client.host if request.client else None
        )
        return {
            "success": True,
            "message": f"Clone creato: {clone_dataset}",
            "clone_dataset": clone_dataset,
            "source_snapshot": full_snapshot
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Errore clone: {result.stderr or result.stdout}"
        )


@router.delete("/{job_id}/snapshots/{snapshot_name}")
async def delete_snapshot(
    job_id: int,
    snapshot_name: str,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina una snapshot specifica dal dataset destinazione."""
    from services.ssh_service import ssh_service
    
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    if not dest_node:
        raise HTTPException(status_code=404, detail="Nodo destinazione non trovato")
    
    full_snapshot = f"{job.dest_dataset}@{snapshot_name}"
    
    # Rilascia eventuale hold e poi elimina snapshot
    del_cmd = f"zfs release keep {full_snapshot} 2>/dev/null; zfs destroy {full_snapshot}"
    
    result = await ssh_service.execute(
        hostname=dest_node.hostname,
        command=del_cmd,
        port=dest_node.ssh_port,
        username=dest_node.ssh_user,
        key_path=dest_node.ssh_key_path,
        timeout=120
    )
    
    if result.success:
        log_audit(
            db, user.id, "snapshot_delete", "sync_job",
            resource_id=job_id,
            details=f"Eliminata snapshot {snapshot_name} da {dest_node.name}:{job.dest_dataset}",
            ip_address=request.client.host if request.client else None
        )
        return {"success": True, "message": f"Snapshot {snapshot_name} eliminata"}
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Errore eliminazione: {result.stderr or result.stdout}"
        )
