"""
Scheduler Service - Gestione job schedulati
Con supporto notifiche e riepilogo giornaliero
"""

import asyncio
from datetime import datetime, time
from typing import Dict, Optional, Callable
import logging
from croniter import croniter
from sqlalchemy.orm import Session

from database import SessionLocal, SyncJob, JobLog, Node, NotificationConfig, SystemConfig, HostBackupJob, MigrationJob
from services.syncoid_service import syncoid_service
from services.proxmox_service import proxmox_service
from services.notification_service import notification_service
from services.host_backup_service import host_backup_service
from services.host_info_service import host_info_service
from services.cache_service import cache_service

logger = logging.getLogger(__name__)

# Finestra (secondi) dopo l'inizio di uno slot cron in cui un restart può
# ancora innescare la run di quello slot (evita backlog di settimane).
_CRON_SLOT_GRACE_SEC = 120


def compute_initial_next_run(
    schedule: str,
    last_run: Optional[datetime],
    now: datetime,
) -> datetime:
    """Calcola la prossima esecuzione senza sparare tutti i cron arretrati al restart.

    - Se siamo entro _CRON_SLOT_GRACE_SEC dall'inizio dello slot corrente e
      last_run è anterior allo slot → due now (run nello slot appena iniziato).
    - Altrimenti → prossimo slot futuro da now (niente catch-up multi-giorno/settimana).
    """
    itr = croniter(schedule, now)
    next_future = itr.get_next(datetime)
    prev_slot = itr.get_prev(datetime)
    if (last_run is None or last_run < prev_slot) and (now - prev_slot).total_seconds() <= _CRON_SLOT_GRACE_SEC:
        return prev_slot
    return next_future


class SchedulerService:
    """Servizio per scheduling dei job di sincronizzazione"""
    
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._jobs: Dict[str, datetime] = {}  # job_key -> next_run
        # Lock di esecuzione: previene il fire concorrente dello stesso
        # job (race scheduler vs durata > intervallo cron). Le chiavi sono
        # le stesse usate per `_jobs` (es. "sync_42", "backup_pbs_3").
        self._running_jobs: set = set()
        self._last_daily_summary: Optional[datetime] = None
        self._last_vm_cache_refresh: Optional[datetime] = None
        self._daily_summary_hour: int = 8  # Ora predefinita: 08:00 UTC
        self._daily_summary_enabled: bool = True

    async def start(self):
        """Avvia lo scheduler"""
        if self._running:
            return

        # Pulizia di job rimasti in stato `running` da un crash precedente.
        # Senza questo step un crash del backend lascia per sempre i job
        # come "in esecuzione" e impedisce nuove run.
        self._reset_stale_running_jobs()

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        self._last_sync_reconcile: Optional[datetime] = None
        asyncio.create_task(self._reconcile_sync_jobs_on_startup())
        logger.info("Scheduler avviato")

        # Carica configurazione orario riepilogo
        self._load_daily_summary_config()

    def _reset_stale_running_jobs(self) -> None:
        """All'avvio, marca come failed/idle i job lasciati in stato
        'running' o 'backing_up'/'restoring'/'registering' da un crash.
        """
        from database import RecoveryJob, BackupJob  # lazy import per evitare cicli
        db = SessionLocal()
        try:
            stale_msg = "reset allo startup (backend riavviato durante esecuzione)"
            # SyncJob: NON resettare qui — syncoid puo' continuare sui nodi
            # remoti dopo restart del manager. Riconciliazione async dedicata.
            # RecoveryJob / BackupJob hanno current_status enumerato.
            for rj in db.query(RecoveryJob).filter(
                RecoveryJob.current_status.in_(["backing_up", "restoring", "registering", "running"])
            ).all():
                rj.current_status = "failed"
                rj.last_status = "failed"
                rj.last_error = stale_msg
            for bj in db.query(BackupJob).filter(
                BackupJob.current_status.in_(["running", "backing_up"])
            ).all():
                bj.current_status = "failed"
                bj.last_status = "failed"
                bj.last_error = stale_msg
            db.commit()
            logger.info("Stato job stale (running/in-progress) riazzerato")
        except Exception as e:
            logger.warning(f"Reset stale jobs fallito: {e}")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()

    async def _reconcile_sync_jobs_on_startup(self) -> None:
        """Allinea stato DB con syncoid/receive realmente attivi sui nodi."""
        from routers.sync_jobs import reconcile_sync_jobs_after_restart
        await reconcile_sync_jobs_after_restart()

    async def _reconcile_stuck_sync_jobs(self) -> None:
        """Ogni ~2 min chiude job al 100% senza processi attivi o riavvia monitor."""
        now = datetime.utcnow()
        last = getattr(self, "_last_sync_reconcile", None)
        if last and (now - last).total_seconds() < 120:
            return
        self._last_sync_reconcile = now
        try:
            from routers.sync_jobs import _reconcile_running_sync_jobs_once, _reconcile_pending_vm_registrations
            await _reconcile_running_sync_jobs_once()
            await _reconcile_pending_vm_registrations()
        except Exception as e:
            logger.warning(f"Reconcile sync jobs periodico fallito: {e}")

    def _try_lock(self, key: str) -> bool:
        """Acquisisce il lock di esecuzione per un job. Ritorna False se
        il job e' gia' in esecuzione (no double-fire)."""
        if key in self._running_jobs:
            return False
        self._running_jobs.add(key)
        return True

    def _unlock(self, key: str) -> None:
        self._running_jobs.discard(key)

    async def _guarded_execute(self, key: str, fn: Callable, *args):
        """Esegue `fn(*args)` rilasciando sempre il lock alla fine,
        anche su eccezione. Le exception vengono solo loggate per non
        far propagare errori al loop principale."""
        try:
            await fn(*args)
        except Exception as e:
            logger.error(f"Job {key} fallito: {e}", exc_info=True)
        finally:
            self._unlock(key)

    def is_running(self, key: str) -> bool:
        """API pubblica: verifica se un job e' attualmente in esecuzione
        secondo lo scheduler in-memory. Usata dagli endpoint /run-now per
        evitare double-fire manuale.
        """
        return key in self._running_jobs

    def mark_running(self, key: str) -> bool:
        """API pubblica per i router: tenta di acquisire il lock.
        Ritorna False se gia' in esecuzione."""
        return self._try_lock(key)

    def mark_done(self, key: str) -> None:
        self._unlock(key)
    
    async def stop(self):
        """Ferma lo scheduler"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler fermato")
    
    def _load_daily_summary_config(self):
        """Carica la configurazione dell'orario del riepilogo giornaliero"""
        db = SessionLocal()
        try:
            # Orario
            hour_config = db.query(SystemConfig).filter(
                SystemConfig.key == "daily_summary_hour"
            ).first()
            if hour_config and hour_config.value:
                try:
                    self._daily_summary_hour = int(hour_config.value)
                except ValueError:
                    pass
            
            # Abilitato/Disabilitato
            enabled_config = db.query(SystemConfig).filter(
                SystemConfig.key == "daily_summary_enabled"
            ).first()
            self._daily_summary_enabled = True
            if enabled_config and enabled_config.value:
                self._daily_summary_enabled = enabled_config.value.lower() in ("true", "1", "yes")
            
            if self._daily_summary_enabled:
                logger.info(f"Riepilogo giornaliero schedulato alle ore {self._daily_summary_hour}:00 UTC")
            else:
                logger.info("Riepilogo giornaliero disabilitato")
        finally:
            db.close()
    
    async def _scheduler_loop(self):
        """Loop principale dello scheduler"""
        while self._running:
            try:
                await self._check_and_run_jobs()
                await self._check_daily_summary()
                await self._check_host_info_updates()
                await self._refresh_vm_cache()
                await self._daily_log_cleanup()
                await self._reconcile_stuck_sync_jobs()
                await asyncio.sleep(60)  # Check ogni minuto
            except Exception as e:
                logger.error(f"Errore nello scheduler: {e}")
                await asyncio.sleep(60)

    async def _daily_log_cleanup(self):
        """Una volta al giorno (UTC 03:30) cancella JobLog/AuditLog scaduti.
        Evita la crescita illimitata del DB in produzione.
        """
        now = datetime.utcnow()
        if now.hour != 3 or now.minute < 30 or now.minute >= 31:
            return
        # Doppia chiamata nel minuto: traccia ultima esecuzione.
        if getattr(self, "_last_log_cleanup", None):
            last = self._last_log_cleanup
            if (now - last).total_seconds() < 12 * 3600:
                return
        self._last_log_cleanup = now
        try:
            from update_db_schema import cleanup_old_logs
            counts = await asyncio.get_event_loop().run_in_executor(
                None, cleanup_old_logs, 30, 90
            )
            logger.info(f"Log cleanup: {counts}")
        except Exception as e:
            logger.warning(f"Log cleanup fallito: {e}")
    
    async def _check_daily_summary(self):
        """Verifica se è ora di inviare il riepilogo giornaliero"""
        # Verifica se abilitato
        if not self._daily_summary_enabled:
            return
        
        now = datetime.utcnow()
        current_hour = now.hour
        
        # Verifica se è l'ora giusta e se non è già stato inviato oggi
        if current_hour == self._daily_summary_hour:
            # Controlla se già inviato oggi
            if self._last_daily_summary:
                if self._last_daily_summary.date() == now.date():
                    return  # Già inviato oggi
            
            # Ricarica configurazione (potrebbe essere cambiata)
            self._load_daily_summary_config()
            if not self._daily_summary_enabled:
                return
            
            # Invia riepilogo
            logger.info("Invio riepilogo giornaliero...")
            try:
                result = await notification_service.send_daily_summary()
                if result.get("sent"):
                    logger.info(f"Riepilogo giornaliero inviato: {result.get('channels', {})}")
                else:
                    logger.debug(f"Riepilogo non inviato: {result.get('reason')}")
                self._last_daily_summary = now
            except Exception as e:
                logger.error(f"Errore invio riepilogo giornaliero: {e}")

    async def _check_host_info_updates(self):
        """Aggiorna i dati dei nodi una volta al giorno (03:00 UTC)"""
        now = datetime.utcnow()
        # Esegui alle 03:00
        if now.hour == 3 and now.minute == 0:
             # Controlla se già eseguito oggi per evitare loop nel minuto 0
             # Usiamo una variabile di stato in memoria per semplicità o controlliamo l'ultimo update di un nodo
             # Per robustezza, meglio limitare la frequenza a 1 volta ogni ora se serve
             pass

        # Approccio più semplice: 
        # Iteriamo i nodi, se last_update è vecchio di > 24h (o nullo), aggiorna.
        # Così è resiliente ai riavvii e non serve cron preciso.
        
        db = SessionLocal()
        try:
            nodes = db.query(Node).filter(Node.is_active == True, Node.is_online == True).all()
            for node in nodes:
                should_update = False
                if not node.host_info_updated_at:
                    should_update = True
                else:
                    delta = now - node.host_info_updated_at
                    if delta.total_seconds() > 86400: # 24 ore
                        should_update = True # Scaduto
                    elif now.hour == 3 and delta.total_seconds() > 3600: 
                        # Se sono le 3 di notte e non ho aggiornato nell'ultima ora -> forza update "giornaliero"
                        should_update = True

                if should_update:
                    logger.info(f"Schedulato aggiornamento dati per nodo {node.name}")
                    asyncio.create_task(host_info_service.update_host_details(node.id))
                    
        except Exception as e:
            logger.error(f"Errore check updates nodi: {e}")
        finally:
            db.close()
    
    async def _refresh_vm_cache(self):
        """Aggiorna la cache VM ogni 5 minuti per velocizzare la pagina VM"""
        now = datetime.utcnow()
        
        # Check se è passato abbastanza tempo dall'ultimo refresh (5 minuti)
        if self._last_vm_cache_refresh:
            delta = (now - self._last_vm_cache_refresh).total_seconds()
            if delta < 300:  # 5 minuti
                return
        
        logger.debug("Avvio refresh cache VMs...")
        db = SessionLocal()
        try:
            await cache_service.refresh_all_nodes(db)
            self._last_vm_cache_refresh = now
            logger.info("Cache VM aggiornata con successo")
        except Exception as e:
            logger.error(f"Errore refresh cache VM: {e}")
        finally:
            db.close()
    
    async def _check_and_run_jobs(self):
        """Verifica e esegue i job schedulati"""
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            
            # === SYNC JOBS ===
            sync_jobs = db.query(SyncJob).filter(
                SyncJob.is_active == True,
                SyncJob.schedule.isnot(None),
                SyncJob.schedule != ""
            ).all()
            
            seen_vm_groups: set[str] = set()
            for job in sync_jobs:
                try:
                    if job.vm_group_id:
                        if job.vm_group_id in seen_vm_groups:
                            continue
                        seen_vm_groups.add(job.vm_group_id)
                        group_key = f"vmgroup_{job.vm_group_id}"
                        if group_key not in self._jobs:
                            self._jobs[group_key] = compute_initial_next_run(
                                job.schedule, job.last_run, now
                            )
                        next_run = self._jobs[group_key]
                        if now >= next_run:
                            if self._try_lock(group_key):
                                logger.info(
                                    f"Esecuzione VM group schedulato: {job.vm_group_id} "
                                    f"(es. {job.name})"
                                )
                                asyncio.create_task(
                                    self._guarded_execute(
                                        group_key,
                                        self._execute_vm_group_sync,
                                        job.vm_group_id,
                                    )
                                )
                            else:
                                logger.info(
                                    f"VM group {job.vm_group_id} ancora in esecuzione: skip"
                                )
                            cron = croniter(job.schedule, now)
                            self._jobs[group_key] = cron.get_next(datetime)
                            for sj in sync_jobs:
                                if sj.vm_group_id == job.vm_group_id:
                                    sk = f"sync_{sj.id}"
                                    self._jobs[sk] = self._jobs[group_key]
                        continue

                    job_key = f"sync_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run, now
                        )
                    
                    next_run = self._jobs[job_key]
                    
                    if now >= next_run:
                        if self._try_lock(job_key):
                            logger.info(f"Esecuzione SyncJob schedulato: {job.name} (ID: {job.id})")
                            asyncio.create_task(self._guarded_execute(job_key, self._execute_job, job.id))
                        else:
                            logger.info(f"SyncJob {job.id} ancora in esecuzione: skip fire schedulato")
                        cron = croniter(job.schedule, now)
                        self._jobs[job_key] = cron.get_next(datetime)
                        
                except Exception as e:
                    logger.error(f"Errore scheduling SyncJob {job.id}: {e}")
            
            # === HOST BACKUP JOBS ===
            host_backup_jobs = db.query(HostBackupJob).filter(
                HostBackupJob.is_active == True,
                HostBackupJob.schedule.isnot(None),
                HostBackupJob.schedule != ""
            ).all()
            
            for job in host_backup_jobs:
                try:
                    job_key = f"host_backup_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run, now
                        )
                    
                    next_run = self._jobs[job_key]
                    
                    if now >= next_run:
                        if self._try_lock(job_key):
                            logger.info(f"Esecuzione HostBackupJob schedulato: {job.name} (ID: {job.id})")
                            asyncio.create_task(self._guarded_execute(job_key, self._execute_host_backup_job, job.id))
                        else:
                            logger.info(f"HostBackupJob {job.id} ancora in esecuzione: skip fire schedulato")
                        cron = croniter(job.schedule, now)
                        self._jobs[job_key] = cron.get_next(datetime)
                        
                except Exception as e:
                    logger.error(f"Errore scheduling HostBackupJob {job.id}: {e}")
            
            # === MIGRATION JOBS ===
            migration_jobs = db.query(MigrationJob).filter(
                MigrationJob.is_active == True,
                MigrationJob.schedule.isnot(None),
                MigrationJob.schedule != ""
            ).all()
            
            for job in migration_jobs:
                try:
                    job_key = f"migration_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run, now
                        )
                    
                    next_run = self._jobs[job_key]
                    
                    if now >= next_run:
                        if self._try_lock(job_key):
                            logger.info(f"Esecuzione MigrationJob schedulato: {job.name} (ID: {job.id})")
                            asyncio.create_task(self._guarded_execute(job_key, self._execute_migration_job, job.id))
                        else:
                            logger.info(f"MigrationJob {job.id} ancora in esecuzione: skip fire schedulato")
                        cron = croniter(job.schedule, now)
                        self._jobs[job_key] = cron.get_next(datetime)
                        
                except Exception as e:
                    logger.error(f"Errore scheduling MigrationJob {job.id}: {e}")
                    
        finally:
            db.close()
    
    async def _execute_job(self, job_id: int):
        """Esegue un job di sincronizzazione"""
        db = SessionLocal()
        log_entry = None
        
        try:
            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if not job:
                logger.error(f"Job {job_id} non trovato")
                return
            
            source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
            dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
            
            if not source_node or not dest_node:
                logger.error(f"Nodi non trovati per job {job_id}")
                return
            
            # Crea log entry
            log_entry = JobLog(
                job_type="sync",
                job_id=job_id,
                node_name=f"{source_node.name} -> {dest_node.name}",
                dataset=f"{job.source_dataset} -> {job.dest_dataset}",
                status="started",
                message=f"Sincronizzazione avviata"
            )
            db.add(log_entry)
            db.commit()
            
            # Aggiorna stato job
            job.last_status = "running"
            if hasattr(job, "current_status"):
                try:
                    job.current_status = "running"
                except Exception:
                    pass
            # last_run impostato all'avvio (non a fine) cosi' un crash
            # non fa rifire il cron immediatamente al riavvio.
            job.last_run = datetime.utcnow()
            db.commit()
            
            # Determina da dove eseguire (sorgente)
            executor_host = source_node.hostname
            
            # Esegui sync
            result = await syncoid_service.run_sync(
                executor_host=executor_host,
                source_host=None,  # Locale all'executor
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
            
            # Aggiorna job (NB: last_run e' gia' stato settato in apertura)
            job.last_duration = result["duration"]
            job.last_transferred = result.get("transferred")
            job.run_count += 1

            if result["success"]:
                job.last_status = "success"
                if hasattr(job, "current_status"):
                    try:
                        job.current_status = "success"
                    except Exception:
                        pass
                log_entry.status = "success"
                log_entry.message = "Sincronizzazione completata"

                # Registra VM se richiesto
                if job.register_vm and job.vm_id:
                    await self._register_vm_after_sync(db, job, source_node, dest_node, log_entry)
            else:
                job.last_status = "failed"
                if hasattr(job, "current_status"):
                    try:
                        job.current_status = "failed"
                    except Exception:
                        pass
                job.error_count += 1
                log_entry.status = "failed"
                log_entry.message = "Sincronizzazione fallita"
                log_entry.error = result.get("error", "")
            
            log_entry.output = result.get("output", "")
            log_entry.duration = result["duration"]
            log_entry.transferred = result.get("transferred")
            log_entry.completed_at = datetime.utcnow()
            
            db.commit()
            
            # Invia notifica job completato
            # Rispetta notify_mode del job: daily, always, failure, never
            try:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="success" if result["success"] else "failed",
                    source=f"{source_node.name}:{job.source_dataset}",
                    destination=f"{dest_node.name}:{job.dest_dataset}",
                    duration=result["duration"],
                    error=result.get("error") if not result["success"] else None,
                    details=f"Trasferito: {result.get('transferred', 'N/A')}" if result["success"] else None,
                    job_id=job_id,
                    is_scheduled=True,
                    notify_mode=job.notify_mode or "daily",
                    job_type="sync",
                    source_node_name=source_node.name,
                    dest_node_name=dest_node.name
                )
            except Exception as notify_err:
                logger.warning(f"Errore invio notifica per job {job_id}: {notify_err}")
            
        except Exception as e:
            logger.error(f"Errore esecuzione job {job_id}: {e}")
            if log_entry:
                log_entry.status = "failed"
                log_entry.error = str(e)
                log_entry.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    async def _execute_vm_group_sync(self, vm_group_id: str):
        """Esegue in sequenza tutti i dischi di un gruppo VM."""
        from routers.sync_jobs import execute_vm_group_sync_task
        await execute_vm_group_sync_task(vm_group_id, force_rerun=True)
    
    async def _execute_host_backup_job(self, job_id: int):
        """Esegue un job di host backup schedulato"""
        db = SessionLocal()
        log_entry = None
        
        try:
            job = db.query(HostBackupJob).filter(HostBackupJob.id == job_id).first()
            if not job:
                logger.error(f"HostBackupJob {job_id} non trovato")
                return
            
            node = db.query(Node).filter(Node.id == job.node_id).first()
            if not node:
                logger.error(f"Nodo non trovato per HostBackupJob {job_id}")
                return
            
            # Rileva tipo host
            host_type = await host_backup_service.detect_host_type(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            # Crea log entry
            log_entry = JobLog(
                job_type="host_backup",
                job_id=job_id,
                node_name=node.name,
                dataset=f"config-{host_type}",
                status="running",
                message=f"Backup schedulato configurazione {host_type.upper()} su {node.name}"
            )
            db.add(log_entry)
            
            job.current_status = "running"
            job.run_count += 1
            db.commit()
            
            start_time = datetime.utcnow()
            
            # Esegui backup
            result = await host_backup_service.create_host_backup(
                hostname=node.hostname,
                host_type=host_type,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path,
                dest_path=job.dest_path,
                compress=job.compress,
                encrypt=job.encrypt,
                encrypt_password=job.encrypt_password,
                node_name=node.name
            )
            
            end_time = datetime.utcnow()
            duration = int((end_time - start_time).total_seconds())
            
            if result['success']:
                # Applica retention
                await host_backup_service.apply_retention(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path,
                    backup_path=job.dest_path,
                    keep_last=job.keep_last
                )
                
                job.current_status = "completed"
                job.last_status = "success"
                job.last_backup_time = end_time
                job.last_backup_file = result.get('backup_file')
                job.last_backup_size = result.get('size', 0)
                job.last_run = end_time
                job.last_duration = duration
                job.last_error = None
                
                log_entry.status = "success"
                log_entry.message = f"Backup {host_type.upper()} completato: {result['backup_name']} ({result['size_human']})"
                log_entry.completed_at = end_time
                log_entry.duration = duration
                
                logger.info(f"HostBackupJob {job_id} completato: {result['backup_name']}")
            else:
                job.current_status = "failed"
                job.last_status = "failed"
                job.last_run = end_time
                job.last_duration = duration
                job.last_error = result.get('error')
                job.error_count += 1
                
                log_entry.status = "failed"
                log_entry.error = result.get('error')
                log_entry.message = f"Backup {host_type.upper()} fallito"
                log_entry.completed_at = end_time
                log_entry.duration = duration
                
                logger.error(f"HostBackupJob {job_id} fallito: {result.get('error')}")
            
            db.commit()
            
            # Invia notifica - il notification_service gestisce notify_mode internamente
            try:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status=job.last_status,
                    source=node.name,
                    destination=job.dest_path,
                    duration=duration,
                    error=job.last_error if job.last_status == 'failed' else None,
                    details=f"File: {result.get('backup_name', 'N/A')}, Size: {result.get('size_human', 'N/A')}",
                    job_id=job_id,
                    is_scheduled=True,
                    notify_mode=job.notify_mode or "daily",
                    job_type="host_backup",
                    source_node_name=node.name,
                    dest_node_name=None  # Host backup non ha un nodo destinazione
                )
            except Exception as notify_err:
                logger.warning(f"Errore invio notifica per HostBackupJob {job_id}: {notify_err}")
            
        except Exception as e:
            logger.error(f"Errore esecuzione HostBackupJob {job_id}: {e}")
            if log_entry:
                log_entry.status = "failed"
                log_entry.error = str(e)
                log_entry.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
    
    async def _execute_migration_job(self, job_id: int):
        """Esegue un job di migrazione"""
        from routers.migration_jobs import execute_migration_job_task
        
        # Usa la funzione già definita nel router
        await execute_migration_job_task(job_id, triggered_by=None)
    
    async def _register_vm_after_sync(
        self,
        db: Session,
        job: SyncJob,
        source_node: Node,
        dest_node: Node,
        log_entry: JobLog
    ):
        """Registra una VM sul nodo destinazione dopo la sync.

        BUG FIX (3.16.5):
          - prima il VMID passato a register_vm era SEMPRE quello sorgente
            (`job.vm_id`), ignorando `job.dest_vm_id`. Risultato: la VM
            replicata veniva registrata con il VMID sorgente — l'utente
            si trovava la VM con vmid duplicato e quella scelta nel
            wizard non veniva mai creata.
          - inoltre TUTTI i parametri di registrazione (storage, bridge,
            VLAN, nome, force-cpu) venivano persi perche' a register_vm
            venivano passati solo hostname/vmid/vm_type/config_content.
        """
        try:
            # 1) Config sorgente
            success, config = await proxmox_service.get_vm_config_file(
                hostname=source_node.hostname,
                vmid=job.vm_id,
                vm_type=job.vm_type or "qemu",
                port=source_node.ssh_port,
                username=source_node.ssh_user,
                key_path=source_node.ssh_key_path,
            )
            if not success:
                log_entry.message += " | Registrazione VM fallita: impossibile ottenere config"
                return

            # 2) Bridge esistenti sul dest (per warning)
            try:
                dest_bridges = await proxmox_service.get_node_bridges(
                    hostname=dest_node.hostname,
                    port=dest_node.ssh_port,
                    username=dest_node.ssh_user,
                    key_path=dest_node.ssh_key_path,
                )
            except Exception:
                dest_bridges = None

            # 3) VMID destinazione: dest_vm_id se impostato, altrimenti
            #    quello sorgente.
            target_vmid = job.dest_vm_id or job.vm_id
            dest_zfs_pool = "/".join(job.dest_dataset.split("/")[:-1]) if job.dest_dataset and "/" in job.dest_dataset else job.dest_dataset

            # 4) Registra (passando TUTTI i parametri)
            success, msg, warnings = await proxmox_service.register_vm(
                hostname=dest_node.hostname,
                vmid=target_vmid,
                vm_type=job.vm_type or "qemu",
                config_content=config,
                source_storage=getattr(job, "source_storage", None),
                dest_storage=getattr(job, "dest_storage", None),
                dest_zfs_pool=dest_zfs_pool,
                vm_name_suffix=getattr(job, "dest_vm_name_suffix", None),
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
                log_entry.message += f" | VM {target_vmid} registrata su {dest_node.name}"
                if warnings:
                    log_entry.message += f" [Avvisi: {'; '.join(warnings)}]"
            else:
                log_entry.message += f" | Registrazione VM fallita: {msg}"

        except Exception as e:
            log_entry.message += f" | Errore registrazione VM: {e}"
    
    def _adapt_vm_config(self, config: str, source_dataset: str, dest_dataset: str) -> str:
        """
        Adatta la configurazione VM per il nodo destinazione
        
        Sostituisce i riferimenti allo storage sorgente con quello destinazione
        """
        # Estrai il nome dello storage dal dataset
        # es: rpool/data -> local-zfs (dipende dalla config Proxmox)
        # Per ora ritorniamo la config così com'è
        # In produzione servirebbe una mappatura storage sorgente -> destinazione
        
        return config
    
    def _sync_job_scheduler_key(self, job_id: int, vm_group_id: Optional[str] = None) -> str:
        if vm_group_id:
            return f"vmgroup_{vm_group_id}"
        return f"sync_{job_id}"

    def update_vm_group_schedule(
        self,
        vm_group_id: str,
        schedule: str,
        last_run: Optional[datetime] = None,
    ) -> None:
        """Aggiorna lo schedule in-memory di un gruppo VM."""
        key = f"vmgroup_{vm_group_id}"
        if schedule:
            self._jobs[key] = compute_initial_next_run(schedule, last_run, datetime.utcnow())
        elif key in self._jobs:
            del self._jobs[key]

    def remove_vm_group_schedule(self, vm_group_id: str) -> None:
        self._jobs.pop(f"vmgroup_{vm_group_id}", None)

    def update_job_schedule(
        self,
        job_id: int,
        schedule: str,
        vm_group_id: Optional[str] = None,
        last_run: Optional[datetime] = None,
    ) -> None:
        """Aggiorna lo schedule in-memory di un SyncJob (o del suo gruppo VM)."""
        if vm_group_id:
            self.update_vm_group_schedule(vm_group_id, schedule, last_run)
            return
        key = self._sync_job_scheduler_key(job_id)
        if schedule:
            self._jobs[key] = compute_initial_next_run(schedule, last_run, datetime.utcnow())
        elif key in self._jobs:
            del self._jobs[key]

    def remove_job(self, job_id: int, vm_group_id: Optional[str] = None) -> None:
        """Rimuove le chiavi scheduler di un singolo job disco."""
        self._jobs.pop(f"sync_{job_id}", None)
        if vm_group_id:
            # La chiave vmgroup_ resta finché non si chiama remove_vm_group_schedule.
            pass


# Singleton
scheduler_service = SchedulerService()
