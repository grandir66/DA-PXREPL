"""Esecuzione recovery job PBS (backup + restore + registrazione VM)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from services.recovery_job_helpers import ensure_pbs_storage_registered

logger = logging.getLogger(__name__)


async def execute_recovery_job_task(job_id: int, triggered_by: Optional[int] = None):
    """
    Task asincrono per eseguire un recovery job completo con logging dettagliato.
    Sequenza: Backup -> Attesa completamento -> Restore -> Registrazione VM
    
    Ogni fase viene registrata con log separati per tracciabilità completa.
    """
    from database import SessionLocal
    from services.notification_service import notification_service
    
    db = SessionLocal()
    log_entry_main = None
    log_entry_backup = None
    log_entry_restore = None
    
    try:
        job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
        if not job:
            logger.error(f"Recovery job {job_id} non trovato")
            return
        
        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
        
        if not source_node or not pbs_node or not dest_node:
            logger.error(f"Nodi non trovati per recovery job {job_id}")
            return
        
        # ========== FASE 0: PREPARAZIONE ==========
        logger.info(f"[Recovery Job {job_id}] === FASE 0: PREPARAZIONE ===")
        logger.info(f"[Recovery Job {job_id}] VM: {job.vm_id} ({job.vm_type})")
        logger.info(f"[Recovery Job {job_id}] Sorgente: {source_node.name} ({source_node.hostname})")
        logger.info(f"[Recovery Job {job_id}] PBS: {pbs_node.name} ({pbs_node.hostname})")
        logger.info(f"[Recovery Job {job_id}] Destinazione: {dest_node.name} ({dest_node.hostname})")
        
        # Log principale (overall)
        log_entry_main = JobLog(
            job_type="recovery",
            job_id=job_id,
            node_name=f"{source_node.name} -> {dest_node.name}",
            status="started",
            message=f"Avvio recovery VM {job.vm_id} ({job.vm_type}) da {source_node.name} a {dest_node.name} via PBS {pbs_node.name}",
            triggered_by=triggered_by
        )
        db.add(log_entry_main)
        job.current_status = RecoveryJobStatus.PENDING.value
        job.last_run = datetime.utcnow()
        db.commit()
        
        start_time = datetime.utcnow()
        datastore = job.pbs_datastore or pbs_node.pbs_datastore or "datastore1"
        
        logger.info(f"[Recovery Job {job_id}] Datastore PBS: {datastore}")
        logger.info(f"[Recovery Job {job_id}] Storage PBS: {job.pbs_storage_id or 'auto-create'}")
        
        # ========== FASE 1: BACKUP ==========
        logger.info(f"[Recovery Job {job_id}] === FASE 1: BACKUP ===")
        logger.info(f"[Recovery Job {job_id}] Avvio backup VM {job.vm_id} su nodo {source_node.name}")
        
        job.current_status = RecoveryJobStatus.BACKING_UP.value
        db.commit()
        
        # Log specifico per fase backup
        log_entry_backup = JobLog(
            job_type="backup",
            job_id=job_id,
            node_name=source_node.name,
            dataset=f"vm/{job.vm_id}",
            status="started",
            message=f"Backup VM {job.vm_id} verso PBS {pbs_node.name} (datastore: {datastore})",
            triggered_by=triggered_by
        )
        db.add(log_entry_backup)
        db.commit()
        
        backup_start = datetime.utcnow()
        
        # Esegui backup
        # NOTE: Don't pass pbs_storage_id here - let it auto-detect on source node
        # The stored pbs_storage_id is for the destination node, not source
        backup_result = await pbs_service.run_backup(
            source_node_hostname=source_node.hostname,
            vm_id=job.vm_id,
            pbs_hostname=pbs_node.hostname,
            datastore=datastore,
            pbs_user=pbs_node.pbs_username or f"{pbs_node.ssh_user}@pam",
            pbs_password=pbs_node.pbs_password,
            pbs_fingerprint=pbs_node.pbs_fingerprint,
            pbs_storage_id=None,  # Auto-detect on source node
            vm_type=job.vm_type,
            mode=job.backup_mode,
            compress=job.backup_compress,
            source_node_port=source_node.ssh_port,
            source_node_user=source_node.ssh_user,
            source_node_key=source_node.ssh_key_path
        )
        
        backup_duration = int((datetime.utcnow() - backup_start).total_seconds())
        
        # Aggiorna log backup
        if backup_result["success"]:
            log_entry_backup.status = "success"
            log_entry_backup.message = f"Backup completato: {backup_result.get('backup_id', 'N/A')}"
            log_entry_backup.backup_id = backup_result.get("backup_id")
            log_entry_backup.duration = backup_duration
            log_entry_backup.output = backup_result.get("output", "")[:5000]  # Limita output
            logger.info(f"[Recovery Job {job_id}] ✓ Backup completato in {backup_duration}s - ID: {backup_result.get('backup_id')}")
        else:
            log_entry_backup.status = "failed"
            log_entry_backup.message = f"Backup fallito: {backup_result.get('error', 'Unknown error')}"
            log_entry_backup.error = backup_result.get("error", backup_result.get("message", ""))[:2000]
            log_entry_backup.duration = backup_duration
            log_entry_backup.output = backup_result.get("output", "")[:5000]
            logger.error(f"[Recovery Job {job_id}] ✗ Backup fallito: {backup_result.get('error')}")
        
        log_entry_backup.completed_at = datetime.utcnow()
        db.commit()
        
        if not backup_result["success"]:
            # Backup fallito, termina qui
            job.current_status = RecoveryJobStatus.FAILED.value
            job.last_status = "failed"
            job.last_error = f"Backup fallito: {backup_result.get('error', 'Unknown error')}"
            job.error_count += 1
            job.consecutive_failures += 1
            job.last_duration = backup_duration
            
            log_entry_main.status = "failed"
            log_entry_main.message = f"Recovery fallito nella fase backup: {backup_result.get('error')}"
            log_entry_main.error = backup_result.get("error", "")[:2000]
            log_entry_main.duration = backup_duration
            log_entry_main.completed_at = datetime.utcnow()
            db.commit()
            
            # Notifica fallimento
            if job.notify_on_each_run:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="failed",
                    source=f"{source_node.name}:vm/{job.vm_id}",
                    destination=f"{dest_node.name}:vm/{job.dest_vm_id or job.vm_id}",
                    duration=backup_duration,
                    error=backup_result.get("error"),
                    details=f"Fase: Backup\n{backup_result.get('output', '')[:500]}",
                    job_id=job_id,
                    is_scheduled=bool(job.schedule),
                    notify_mode=job.notify_mode or "daily",
                    job_type="recovery",
                    source_node_name=source_node.name,
                    dest_node_name=dest_node.name,
                    vm_name=job.vm_name,
                    vm_id=job.vm_id
                )
            
            return
        
        # Backup riuscito, aggiorna job
        job.last_backup_time = datetime.utcnow()
        job.last_backup_id = backup_result.get("backup_id")
        backup_id = backup_result.get("backup_id")
        
        # ========== FASE 2: RESTORE ==========
        logger.info(f"[Recovery Job {job_id}] === FASE 2: RESTORE ===")
        logger.info(f"[Recovery Job {job_id}] Backup ID: {backup_id}")
        logger.info(f"[Recovery Job {job_id}] Avvio restore su nodo {dest_node.name}")
        
        job.current_status = RecoveryJobStatus.RESTORING.value
        db.commit()
        
        # Log specifico per fase restore
        log_entry_restore = JobLog(
            job_type="restore",
            job_id=job_id,
            node_name=dest_node.name,
            dataset=f"vm/{job.dest_vm_id or job.vm_id}",
            status="started",
            message=f"Restore VM {job.vm_id} da PBS {pbs_node.name} (backup: {backup_id})",
            backup_id=backup_id,
            triggered_by=triggered_by
        )
        db.add(log_entry_restore)
        db.commit()
        
        restore_start = datetime.utcnow()
        
        # Assicura storage PBS sul nodo destinazione
        try:
            storage_name = await ensure_pbs_storage_registered(dest_node, job.pbs_storage_id, pbs_node, datastore)
            if storage_name != job.pbs_storage_id:
                job.pbs_storage_id = storage_name
                db.commit()
        except Exception as storage_error:
            logger.error(f"[Recovery Job {job_id}] Impossibile registrare storage PBS: {storage_error}")
            job.current_status = RecoveryJobStatus.FAILED.value
            job.last_status = "failed"
            job.last_error = str(storage_error)[:1000]
            log_entry_main.status = "failed"
            log_entry_main.message = f"Storage PBS non disponibile: {storage_error}"
            log_entry_main.error = str(storage_error)[:2000]
            log_entry_main.completed_at = datetime.utcnow()
            db.commit()
            if job.notify_on_each_run:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="failed",
                    source=f"{source_node.name}:vm/{job.vm_id}",
                    destination=f"{dest_node.name}:vm/{job.dest_vm_id or job.vm_id}",
                    duration=0,
                    error=str(storage_error),
                    details="Storage PBS non configurato sul nodo destinazione",
                    job_id=job_id,
                    is_scheduled=bool(job.schedule),
                    notify_mode=job.notify_mode or "daily",
                    job_type="recovery",
                    source_node_name=source_node.name,
                    dest_node_name=dest_node.name,
                    vm_name=job.vm_name,
                    vm_id=job.vm_id
                )
            return

        # Esegui restore
        restore_result = await pbs_service.run_restore(
            dest_node_hostname=dest_node.hostname,
            vm_id=job.vm_id,
            pbs_hostname=pbs_node.hostname,
            datastore=datastore,
            backup_id=backup_id,
            pbs_user=pbs_node.pbs_username or f"{pbs_node.ssh_user}@pam",
            pbs_password=pbs_node.pbs_password,
            pbs_fingerprint=pbs_node.pbs_fingerprint,
            pbs_storage_id=job.pbs_storage_id,
            dest_vm_id=job.dest_vm_id,
            dest_vm_name_suffix=job.dest_vm_name_suffix,
            dest_storage=job.dest_storage,
            vm_type=job.vm_type,
            start_vm=job.restore_start_vm,
            unique=job.restore_unique,
            overwrite=job.overwrite_existing,
            dest_node_port=dest_node.ssh_port,
            dest_node_user=dest_node.ssh_user,
            dest_node_key=dest_node.ssh_key_path
        )
        
        restore_duration = int((datetime.utcnow() - restore_start).total_seconds())
        
        # Aggiorna log restore
        if restore_result["success"]:
            log_entry_restore.status = "success"
            log_entry_restore.message = f"Restore completato: VM {restore_result.get('vm_id')} registrata"
            log_entry_restore.duration = restore_duration
            log_entry_restore.output = restore_result.get("output", "")[:5000]
            logger.info(f"[Recovery Job {job_id}] ✓ Restore completato in {restore_duration}s - VMID: {restore_result.get('vm_id')}")
        else:
            log_entry_restore.status = "failed"
            log_entry_restore.message = f"Restore fallito: {restore_result.get('error', 'Unknown error')}"
            log_entry_restore.error = restore_result.get("error", restore_result.get("message", ""))[:2000]
            log_entry_restore.duration = restore_duration
            log_entry_restore.output = restore_result.get("output", "")[:5000]
            logger.error(f"[Recovery Job {job_id}] ✗ Restore fallito: {restore_result.get('error')}")
        
        log_entry_restore.completed_at = datetime.utcnow()
        db.commit()
        
        if not restore_result["success"]:
            # Restore fallito
            job.current_status = RecoveryJobStatus.FAILED.value
            job.last_status = "failed"
            job.last_error = f"Restore fallito: {restore_result.get('error', 'Unknown error')}"
            job.error_count += 1
            job.consecutive_failures += 1
            
            total_duration = int((datetime.utcnow() - start_time).total_seconds())
            job.last_duration = total_duration
            
            log_entry_main.status = "failed"
            log_entry_main.message = f"Recovery fallito nella fase restore: {restore_result.get('error')}"
            log_entry_main.error = restore_result.get("error", "")[:2000]
            log_entry_main.duration = total_duration
            log_entry_main.completed_at = datetime.utcnow()
            db.commit()
            
            # Notifica fallimento
            if job.notify_on_each_run:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="failed",
                    source=f"{source_node.name}:vm/{job.vm_id}",
                    destination=f"{dest_node.name}:vm/{job.dest_vm_id or job.vm_id}",
                    duration=total_duration,
                    error=restore_result.get("error"),
                    details=f"Fase: Restore\nBackup ID: {backup_id}\n{restore_result.get('output', '')[:500]}",
                    job_id=job_id,
                    is_scheduled=bool(job.schedule),
                    notify_mode=job.notify_mode or "daily",
                    job_type="recovery",
                    source_node_name=source_node.name,
                    dest_node_name=dest_node.name,
                    vm_name=job.vm_name,
                    vm_id=job.vm_id
                )
            
            return
        
        # ========== FASE 3: COMPLETAMENTO ==========
        logger.info(f"[Recovery Job {job_id}] === FASE 3: COMPLETAMENTO ===")
        
        job.current_status = RecoveryJobStatus.COMPLETED.value
        job.last_status = "success"
        job.last_error = None
        job.consecutive_failures = 0
        job.last_restore_time = datetime.utcnow()
        job.run_count += 1
        
        total_duration = int((datetime.utcnow() - start_time).total_seconds())
        job.last_duration = total_duration
        
        # Log principale successo
        log_entry_main.status = "success"
        log_entry_main.message = f"Recovery completata: Backup {backup_id} -> Restore VM {restore_result.get('vm_id')}"
        log_entry_main.duration = total_duration
        log_entry_main.backup_id = backup_id
        log_entry_main.completed_at = datetime.utcnow()
        log_entry_main.output = f"Backup: {backup_duration}s | Restore: {restore_duration}s | Totale: {total_duration}s"
        
        db.commit()
        
        logger.info(f"[Recovery Job {job_id}] ✓ Recovery completata in {total_duration}s (Backup: {backup_duration}s, Restore: {restore_duration}s)")
        
        # Notifica successo (solo se configurato)
        if job.notify_on_each_run:
            await notification_service.send_job_notification(
                job_name=job.name,
                status="success",
                source=f"{source_node.name}:vm/{job.vm_id}",
                destination=f"{dest_node.name}:vm/{restore_result.get('vm_id')}",
                duration=total_duration,
                details=f"Backup ID: {backup_id}\nBackup: {backup_duration}s\nRestore: {restore_duration}s",
                job_id=job_id,
                is_scheduled=bool(job.schedule),
                notify_mode=job.notify_mode or "daily",
                job_type="recovery",
                source_node_name=source_node.name,
                dest_node_name=dest_node.name,
                vm_name=job.vm_name,
                vm_id=job.vm_id
            )
        
    except Exception as e:
        logger.exception(f"[Recovery Job {job_id}] Errore critico durante esecuzione: {e}")
        try:
            job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
            if job:
                job.current_status = RecoveryJobStatus.FAILED.value
                job.last_status = "failed"
                job.last_error = f"Errore critico: {str(e)}"
                job.error_count += 1
                job.consecutive_failures += 1
                
                if log_entry_main:
                    log_entry_main.status = "failed"
                    log_entry_main.error = f"Eccezione: {str(e)}"
                    log_entry_main.completed_at = datetime.utcnow()
                
                db.commit()
                
                # Notifica errore critico
                if job.notify_on_each_run:
                    from services.notification_service import notification_service
                    # Recupera nodi per informazioni
                    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
                    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
                    await notification_service.send_job_notification(
                        job_name=job.name,
                        status="failed",
                        source=f"{source_node.name if source_node else 'N/A'}:vm/{job.vm_id}",
                        destination=f"{dest_node.name if dest_node else 'N/A'}:vm/{job.dest_vm_id or job.vm_id}",
                        duration=0,
                        error=f"Errore critico: {str(e)}",
                        job_id=job_id,
                        is_scheduled=bool(job.schedule),
                        notify_mode=job.notify_mode or "daily",
                        job_type="recovery",
                        source_node_name=source_node.name if source_node else None,
                        dest_node_name=dest_node.name if dest_node else None,
                        vm_name=job.vm_name,
                        vm_id=job.vm_id
                    )
        except Exception as inner_e:
            logger.error(f"Errore durante cleanup: {inner_e}")
    finally:
        db.close()
