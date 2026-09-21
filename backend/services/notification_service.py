"""
Notification Service - Servizio centralizzato per invio notifiche
Supporta Email, Webhook e Telegram
"""

import asyncio
import httpx
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
import logging

from services.email_service import email_service
from database import (
    SessionLocal,
    NotificationConfig,
    JobLog,
    SyncJob,
    RecoveryJob,
    FileReplicationJob,
    FileEndpoint,
    Node,
)

logger = logging.getLogger(__name__)


def _in_ritardo(job) -> bool:
    """Il cron si aspettava una corsa che non c'è stata?

    NON è «zero esecuzioni nelle ultime 24 ore»: un job settimanale è fermo
    per sei giorni su sette, e chiamarlo guasto è un allarme falso — successo
    davvero il 2026-09-08, quando il riepilogo ha gridato «6 job non partiti»
    su un impianto in perfetta salute (erano le repliche del lunedì, del
    mercoledì e del venerdì, tutte puntuali).

    La regola giusta è quella di `check_job_overdue`, che il progetto ha già
    e che usa il cron in ora locale: in ritardo **se l'ultima corsa è
    precedente all'ultimo slot atteso**. Riusarla evita di avere due
    definizioni di «in ritardo» che prima o poi si contraddicono.
    """
    from services.replication_health_service import check_job_overdue

    ultima = getattr(job, "last_run", None) or getattr(job, "last_run_at", None)
    stato = getattr(job, "last_status", None) or getattr(job, "last_run_status", None)
    try:
        return bool(
            check_job_overdue(
                getattr(job, "schedule", None),
                ultima,
                is_active=bool(getattr(job, "is_active", True)),
                last_status=stato,
            )["overdue"]
        )
    except Exception as exc:  # noqa: BLE001 — un cron storto non ferma il riepilogo
        logger.debug("Stato «in ritardo» non calcolabile per %s: %s", getattr(job, "name", "?"), exc)
        return False


class NotificationService:
    """Servizio centralizzato per tutte le notifiche"""
    
    def __init__(self):
        self._config: Optional[NotificationConfig] = None
        self._last_config_load: Optional[datetime] = None
        self._config_cache_seconds = 60  # Ricarica config ogni 60 secondi
    
    def _load_config(self) -> Optional[NotificationConfig]:
        """Carica la configurazione notifiche dal database"""
        now = datetime.utcnow()
        
        # Usa cache se recente
        if (self._config and self._last_config_load and 
            (now - self._last_config_load).seconds < self._config_cache_seconds):
            return self._config
        
        db = SessionLocal()
        try:
            self._config = db.query(NotificationConfig).first()
            self._last_config_load = now
            return self._config
        finally:
            db.close()
    
    def _configure_email_service(self, config: NotificationConfig):
        """Configura il servizio email con i dati dal database"""
        if config and config.smtp_enabled and config.smtp_host:
            from services.secrets import decrypt_secret
            email_service.configure(
                host=config.smtp_host,
                port=config.smtp_port or 587,
                user=config.smtp_user,
                password=decrypt_secret(config.smtp_password),
                from_addr=config.smtp_from,
                to_addrs=config.smtp_to,
                subject_prefix=config.smtp_subject_prefix or "[DAPX]",
                use_tls=config.smtp_tls if config.smtp_tls is not None else True
            )
    
    async def send_job_notification(
        self,
        job_name: str,
        status: str,  # success, failed, warning
        source: str,
        destination: str,
        duration: Optional[int] = None,
        error: Optional[str] = None,
        details: Optional[str] = None,
        job_id: Optional[int] = None,
        is_scheduled: bool = False,
        notify_mode: str = "daily",  # daily, always, failure, never
        transferred: Optional[str] = None,  # Dati trasferiti (es: "10.5 GiB")
        job_type: Optional[str] = None,  # Tipo job (sync, backup, migration, recovery)
        source_node_name: Optional[str] = None,
        dest_node_name: Optional[str] = None,
        cluster_name: Optional[str] = None,
        vm_name: Optional[str] = None,
        vm_id: Optional[int] = None,
        notify_subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Invia notifica per un job completato su tutti i canali abilitati.
        
        Args:
            job_name: Nome del job
            status: Stato (success, failed, warning)
            source: Sorgente
            destination: Destinazione
            duration: Durata in secondi
            error: Messaggio errore
            details: Dettagli aggiuntivi
            job_id: ID del job (per tracking notifiche giornaliere)
            is_scheduled: True se job schedulato/ricorrente
            notify_mode: Modalità notifica del job (daily, always, failure, never)
            transferred: Dati trasferiti (es: "10.5 GiB")
            job_type: Tipo job (sync, backup, migration, recovery)
        
        Returns:
            Dict con risultati per ogni canale
        """
        # Verifica notify_mode del job.
        #
        # `daily` vuol dire quel che l'interfaccia ha sempre promesso: «solo nel
        # riepilogo giornaliero». Fino al 2026-09-08 faceva un'altra cosa —
        # mandava una mail SUBITO per ogni job, al massimo una al giorno per i
        # successi — e siccome il riepilogo partiva comunque, chi aveva
        # l'impostazione predefinita riceveva le due cose insieme. L'etichetta
        # mentiva, e il commento su `RecoveryJob.notify_on_each_run` («False =
        # solo report giornaliero») dice che l'intenzione era questa fin
        # dall'inizio. Chi vuole la mail al volo ha `always` o `failure`.
        if notify_mode in ("never", "daily"):
            logger.debug(
                "Nessuna notifica immediata per %s (notify_mode=%s): "
                "l'attività finisce nel riepilogo giornaliero",
                job_name, notify_mode,
            )
            return {"sent": False, "reason": f"notify_mode_{notify_mode}"}

        if notify_mode == "failure" and status != "failed":
            logger.debug(f"Notifica solo per errori, job {job_name} ha status {status}")
            return {"sent": False, "reason": "notify_mode_failure_only"}
        
        config = self._load_config()
        if not config:
            logger.debug("Notifiche non configurate")
            return {"sent": False, "reason": "not_configured"}
        
        # Verifica se notificare in base allo status globale
        should_notify = (
            (status == "success" and config.notify_on_success) or
            (status == "failed" and config.notify_on_failure) or
            (status == "warning" and config.notify_on_warning)
        )
        
        if not should_notify:
            logger.debug(f"Notifica non richiesta per status: {status}")
            return {"sent": False, "reason": f"notify_on_{status}_disabled"}
        
        # Se non forniti, prova a recuperare informazioni dal database usando job_id
        if job_id and (not source_node_name or not dest_node_name or not vm_name):
            db = SessionLocal()
            try:
                # Prova a recuperare informazioni dal job
                if job_type == "sync":
                    from database import SyncJob
                    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
                    if job:
                        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
                        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
                        if source_node and not source_node_name:
                            source_node_name = source_node.name
                        if dest_node and not dest_node_name:
                            dest_node_name = dest_node.name
                        if job.vm_name and not vm_name:
                            vm_name = job.vm_name
                        if job.vm_id and not vm_id:
                            vm_id = job.vm_id
                        if not transferred and getattr(job, "last_transferred", None):
                            transferred = job.last_transferred
                elif job_type == "recovery":
                    from database import RecoveryJob
                    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
                    if job:
                        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
                        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
                        if source_node and not source_node_name:
                            source_node_name = source_node.name
                        if dest_node and not dest_node_name:
                            dest_node_name = dest_node.name
                        if job.vm_name and not vm_name:
                            vm_name = job.vm_name
                        if job.vm_id and not vm_id:
                            vm_id = job.vm_id
                elif job_type == "backup":
                    from database import BackupJob
                    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
                    if job:
                        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
                        if source_node and not source_node_name:
                            source_node_name = source_node.name
                        if job.vm_name and not vm_name:
                            vm_name = job.vm_name
                        if job.vm_id and not vm_id:
                            vm_id = job.vm_id
                elif job_type == "migration":
                    from database import MigrationJob
                    job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
                    if job:
                        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
                        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
                        if source_node and not source_node_name:
                            source_node_name = source_node.name
                        if dest_node and not dest_node_name:
                            dest_node_name = dest_node.name
                        if job.vm_name and not vm_name:
                            vm_name = job.vm_name
                        if job.vm_id and not vm_id:
                            vm_id = job.vm_id
            except Exception as e:
                logger.warning(f"Errore recupero informazioni job dal database: {e}")
            finally:
                db.close()
        
        # Se cluster_name non fornito, usa un default o recupera da configurazione
        if not cluster_name:
            # Prova a recuperare da SystemConfig
            db = SessionLocal()
            try:
                from database import SystemConfig
                cluster_config = db.query(SystemConfig).filter(SystemConfig.key == "cluster_name").first()
                if cluster_config:
                    cluster_name = cluster_config.value
                else:
                    cluster_name = "DAPX Cluster"  # Default
            except Exception as e:
                logger.debug(f"Errore recupero cluster_name: {e}")
                cluster_name = "DAPX Cluster"  # Default
            finally:
                db.close()
        
        results = {"sent": True, "channels": {}}
        
        # Email
        if config.smtp_enabled:
            try:
                self._configure_email_service(config)
                # P-09/P7: smtplib è bloccante → in un thread per non fermare l'event loop.
                success, message = await asyncio.to_thread(
                    email_service.send_job_notification,
                    job_name=job_name,
                    status=status,
                    source=source,
                    destination=destination,
                    duration=duration,
                    error=error,
                    details=details,
                    cluster_name=cluster_name,
                    source_node_name=source_node_name,
                    dest_node_name=dest_node_name,
                    job_type=job_type,
                    vm_name=vm_name,
                    vm_id=vm_id,
                    transferred=transferred,
                    notify_subject=notify_subject,
                )
                results["channels"]["email"] = {"success": success, "message": message}
                if success:
                    logger.info(f"Email notifica inviata per job {job_name}")
                else:
                    logger.error(f"Errore invio email per job {job_name}: {message}")
            except Exception as e:
                logger.error(f"Eccezione invio email: {e}")
                results["channels"]["email"] = {"success": False, "message": str(e)}
        
        # Webhook
        if config.webhook_enabled and config.webhook_url:
            try:
                webhook_result = await self._send_webhook(
                    config=config,
                    event_type="job_completed",
                    data={
                        "job_name": job_name,
                        "status": status,
                        "source": source,
                        "destination": destination,
                        "duration": duration,
                        "error": error,
                        "details": details,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                results["channels"]["webhook"] = webhook_result
            except Exception as e:
                logger.error(f"Eccezione webhook: {e}")
                results["channels"]["webhook"] = {"success": False, "message": str(e)}
        
        # Telegram
        if config.telegram_enabled and config.telegram_bot_token and config.telegram_chat_id:
            try:
                telegram_result = await self._send_telegram(
                    config=config,
                    message=self._format_telegram_job_message(
                        job_name, status, source, destination, duration, error
                    )
                )
                results["channels"]["telegram"] = telegram_result
            except Exception as e:
                logger.error(f"Eccezione telegram: {e}")
                results["channels"]["telegram"] = {"success": False, "message": str(e)}
        
        return results
    
    async def send_replication_overdue_alert(
        self,
        overdue_groups: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Notifica consolidata per VM/gruppi con replica schedulata in ritardo."""
        if not overdue_groups:
            return {"sent": False, "reason": "nothing_overdue"}

        config = self._load_config()
        if not config:
            return {"sent": False, "reason": "not_configured"}
        if not (config.smtp_enabled or config.webhook_enabled or config.telegram_enabled):
            return {"sent": False, "reason": "no_channels_enabled"}
        if not config.notify_on_warning:
            return {"sent": False, "reason": "notify_on_warning_disabled"}

        from services.replication_health_service import descrivi_gruppo_in_ritardo

        details = "\n".join(descrivi_gruppo_in_ritardo(g) for g in overdue_groups)
        title = f"Replica in ritardo — {len(overdue_groups)} VM/gruppi"

        return await self.send_job_notification(
            job_name=title,
            status="warning",
            source="Scheduler DAPX",
            destination="—",
            details=details,
            is_scheduled=True,
            notify_mode="always",
            job_type="sync",
        )

    async def send_uuid_duplicati_alert(
        self,
        duplicati: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Notifica per VM che condividono lo stesso uuid SMBIOS (Veeam le esclude)."""
        if not duplicati:
            return {"sent": False, "reason": "nothing_duplicated"}

        config = self._load_config()
        if not config:
            return {"sent": False, "reason": "not_configured"}
        if not (config.smtp_enabled or config.webhook_enabled or config.telegram_enabled):
            return {"sent": False, "reason": "no_channels_enabled"}
        if not config.notify_on_warning:
            return {"sent": False, "reason": "notify_on_warning_disabled"}

        from services.uuid_duplicati import descrivi_duplicati

        title = f"UUID SMBIOS duplicati — {len(duplicati)} coppie di VM"
        return await self.send_job_notification(
            job_name=title,
            status="warning",
            source="Scheduler DAPX",
            destination="—",
            details=descrivi_duplicati(duplicati),
            is_scheduled=True,
            notify_mode="always",
            job_type="sync",
        )

    async def send_daily_summary(self) -> Dict[str, Any]:
        """
        Invia il riepilogo giornaliero delle attività con dettaglio per ogni job.
        
        Returns:
            Dict con risultati invio
        """
        config = self._load_config()
        if not config:
            logger.debug("Notifiche non configurate per riepilogo giornaliero")
            return {"sent": False, "reason": "not_configured"}
        
        # Verifica se almeno un canale è abilitato
        if not (config.smtp_enabled or config.webhook_enabled or config.telegram_enabled):
            logger.debug("Nessun canale notifiche abilitato")
            return {"sent": False, "reason": "no_channels_enabled"}
        
        # Raccogli dati delle ultime 24 ore
        db = SessionLocal()
        try:
            yesterday = datetime.utcnow() - timedelta(hours=24)
            
            # Ottieni tutti i sync jobs attivi
            sync_jobs = db.query(SyncJob).filter(SyncJob.is_active == True).all()
            recovery_jobs = db.query(RecoveryJob).filter(RecoveryJob.is_active == True).all()
            file_repl_jobs = db.query(FileReplicationJob).filter(FileReplicationJob.is_active == True).all()

            # Moduli aggiuntivi (import lazy: evita dipendenze circolari all'avvio)
            from database import BackupJob, HostBackupJob, MigrationJob, FileEndpoint
            from services.nas_sync.models import NasSyncJob
            from services.vm_snapshot.models import VmSnapshotJob
            backup_pbs_jobs = db.query(BackupJob).filter(BackupJob.is_active == True).all()
            host_backup_jobs = db.query(HostBackupJob).filter(HostBackupJob.is_active == True).all()
            migration_jobs_q = db.query(MigrationJob).filter(MigrationJob.is_active == True).all()
            nas_sync_jobs_q = db.query(NasSyncJob).filter(NasSyncJob.is_active == True).all()
            vm_snapshot_jobs_q = db.query(VmSnapshotJob).filter(VmSnapshotJob.is_active == True).all()

            all_job_lists = [
                sync_jobs, recovery_jobs, file_repl_jobs,
                backup_pbs_jobs, host_backup_jobs, migration_jobs_q,
                nas_sync_jobs_q, vm_snapshot_jobs_q,
            ]
            if not any(all_job_lists):
                logger.info("Nessun job configurato, riepilogo non inviato")
                return {"sent": False, "reason": "no_jobs_configured"}
            
            # Statistiche generali
            total_runs = 0
            successful = 0
            failed = 0
            total_duration = 0
            
            # Dettaglio per ogni job
            jobs_summary = []
            
            # Processa Sync Jobs
            for job in sync_jobs:
                # Ottieni logs per questo job nelle ultime 24 ore
                job_logs = db.query(JobLog).filter(
                    JobLog.job_id == job.id,
                    JobLog.job_type == "sync",
                    JobLog.started_at >= yesterday
                ).order_by(JobLog.started_at.desc()).all()
                
                # Ottieni nodi
                source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
                dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
                
                job_runs = len(job_logs)
                job_success = len([l for l in job_logs if l.status == "success"])
                job_failed = len([l for l in job_logs if l.status == "failed"])
                job_duration = sum(l.duration or 0 for l in job_logs)
                
                # Ultimo errore se presente
                last_error = None
                last_error_time = None
                for log in job_logs:
                    if log.status == "failed" and log.error:
                        last_error = log.error[:200]
                        last_error_time = log.started_at.strftime("%H:%M") if log.started_at else None
                        break
                
                # Ultimo trasferimento
                last_transferred = None
                for log in job_logs:
                    if log.transferred:
                        last_transferred = log.transferred
                        break
                
                job_info = {
                    "id": job.id,
                    "name": job.name,
                    "type": "sync",
                    "notifica": getattr(job, "notify_mode", None) or "daily",
                    "in_ritardo": _in_ritardo(job),
                    "esito_finale": (job_logs[0].status if job_logs else None),
                    "tentativi_max": (
                        max((getattr(l, "attempt_number", 1) or 1) for l in job_logs)
                        if job_logs else 1
                    ),
                    "vm_name": job.vm_name,
                    "vm_id": job.vm_id,
                    "source_node": source_node.name if source_node else "N/A",
                    "dest_node": dest_node.name if dest_node else "N/A",
                    "source_dataset": job.source_dataset,
                    "dest_dataset": job.dest_dataset,
                    "schedule": job.schedule or "Manuale",
                    "runs_24h": job_runs,
                    "success_24h": job_success,
                    "failed_24h": job_failed,
                    "duration_24h": job_duration,
                    "last_status": job.last_status or "never_run",
                    "last_run": job.last_run.strftime("%d/%m %H:%M") if job.last_run else "Mai",
                    "last_transferred": last_transferred or job.last_transferred,
                    "last_error": last_error,
                    "last_error_time": last_error_time
                }
                jobs_summary.append(job_info)
                
                # Aggiungi ai totali
                total_runs += job_runs
                successful += job_success
                failed += job_failed
                total_duration += job_duration
            
            # Processa Recovery Jobs
            for job in recovery_jobs:
                # Ottieni logs per questo job nelle ultime 24 ore
                job_logs = db.query(JobLog).filter(
                    JobLog.job_id == job.id,
                    JobLog.job_type.in_(["recovery", "backup", "restore"]),
                    JobLog.started_at >= yesterday
                ).order_by(JobLog.started_at.desc()).all()
                
                # Ottieni nodi
                source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
                pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
                dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
                
                # Separa log per tipo
                recovery_logs = [l for l in job_logs if l.job_type == "recovery"]
                backup_logs = [l for l in job_logs if l.job_type == "backup"]
                restore_logs = [l for l in job_logs if l.job_type == "restore"]
                
                job_runs = len(recovery_logs)
                job_success = len([l for l in recovery_logs if l.status == "success"])
                job_failed = len([l for l in recovery_logs if l.status == "failed"])
                job_duration = sum(l.duration or 0 for l in recovery_logs)
                
                # Durate fasi
                backup_duration = sum(l.duration or 0 for l in backup_logs)
                restore_duration = sum(l.duration or 0 for l in restore_logs)
                
                # Ultimo errore se presente
                last_error = None
                last_error_time = None
                for log in recovery_logs:
                    if log.status == "failed" and log.error:
                        last_error = log.error[:200]
                        last_error_time = log.started_at.strftime("%H:%M") if log.started_at else None
                        break
                
                job_info = {
                    "id": job.id,
                    "name": job.name,
                    "type": "recovery",
                    "notifica": getattr(job, "notify_mode", None) or "daily",
                    "in_ritardo": _in_ritardo(job),
                    "esito_finale": (recovery_logs[0].status if recovery_logs else None),
                    "tentativi_max": (
                        max((getattr(l, "attempt_number", 1) or 1) for l in recovery_logs)
                        if recovery_logs else 1
                    ),
                    "source_node": source_node.name if source_node else "N/A",
                    "dest_node": dest_node.name if dest_node else "N/A",
                    "pbs_node": pbs_node.name if pbs_node else "N/A",
                    "vm_id": job.vm_id,
                    "vm_name": job.vm_name or f"VM {job.vm_id}",
                    "schedule": job.schedule or "Manuale",
                    "runs_24h": job_runs,
                    "success_24h": job_success,
                    "failed_24h": job_failed,
                    "duration_24h": job_duration,
                    "backup_duration_24h": backup_duration,
                    "restore_duration_24h": restore_duration,
                    "last_status": job.last_status or "never_run",
                    "last_run": job.last_run.strftime("%d/%m %H:%M") if job.last_run else "Mai",
                    "last_error": last_error,
                    "last_error_time": last_error_time
                }
                jobs_summary.append(job_info)
                
                # Aggiungi ai totali
                total_runs += job_runs
                successful += job_success
                failed += job_failed
                total_duration += job_duration

            for job in file_repl_jobs:
                job_logs = db.query(JobLog).filter(
                    JobLog.job_id == job.id,
                    JobLog.job_type == "file_replication",
                    JobLog.started_at >= yesterday,
                ).order_by(JobLog.started_at.desc()).all()

                source = db.query(FileEndpoint).filter(FileEndpoint.id == job.source_endpoint_id).first()
                dest = db.query(FileEndpoint).filter(FileEndpoint.id == job.dest_endpoint_id).first()

                job_runs = len(job_logs)
                job_success = len([l for l in job_logs if l.status == "success"])
                job_failed = len([l for l in job_logs if l.status == "failed"])
                job_duration = sum(l.duration or 0 for l in job_logs)

                last_error = None
                last_error_time = None
                for log in job_logs:
                    if log.status == "failed" and log.error:
                        last_error = log.error[:200]
                        last_error_time = log.started_at.strftime("%H:%M") if log.started_at else None
                        break

                last_transferred = None
                for log in job_logs:
                    if log.transferred:
                        last_transferred = log.transferred
                        break

                paths = job.source_paths or []
                source_paths_label = ", ".join(paths[:2])
                if len(paths) > 2:
                    source_paths_label += f" (+{len(paths) - 2})"

                job_info = {
                    "id": job.id,
                    "name": job.name,
                    "type": "file_replication",
                    "notifica": getattr(job, "notify_mode", None) or "daily",
                    "in_ritardo": _in_ritardo(job),
                    "esito_finale": (job_logs[0].status if job_logs else None),
                    "tentativi_max": (
                        max((getattr(l, "attempt_number", 1) or 1) for l in job_logs)
                        if job_logs else 1
                    ),
                    "source_node": source.name if source else "N/A",
                    "dest_node": dest.name if dest else "N/A",
                    "source_dataset": source_paths_label or "—",
                    "dest_dataset": job.dest_staging_path,
                    "schedule": job.schedule or "Manuale",
                    "runs_24h": job_runs,
                    "success_24h": job_success,
                    "failed_24h": job_failed,
                    "duration_24h": job_duration,
                    "last_status": job.last_run_status or "never_run",
                    "last_run": job.last_run_at.strftime("%d/%m %H:%M") if job.last_run_at else "Mai",
                    "last_transferred": last_transferred,
                    "last_error": last_error,
                    "last_error_time": last_error_time,
                }
                jobs_summary.append(job_info)
                total_runs += job_runs
                successful += job_success
                failed += job_failed
                total_duration += job_duration

            # === Collector generico per i moduli aggiuntivi ===
            def _logs_24h(job_id: int, jtypes: list):
                logs = db.query(JobLog).filter(
                    JobLog.job_id == job_id,
                    JobLog.job_type.in_(jtypes),
                    JobLog.started_at >= yesterday,
                ).order_by(JobLog.started_at.desc()).all()
                runs = len(logs)
                ok = len([l for l in logs if l.status == "success"])
                ko = len([l for l in logs if l.status == "failed"])
                dur = sum(l.duration or 0 for l in logs)
                l_err = l_err_t = None
                for l in logs:
                    if l.status == "failed" and l.error:
                        l_err = l.error[:200]
                        l_err_t = l.started_at.strftime("%H:%M") if l.started_at else None
                        break
                transferred = next(
                    (l.transferred for l in logs if getattr(l, "transferred", None)), None
                )
                # L'esito FINALE (i log arrivano dal più recente) e quanti
                # tentativi sono serviti: senza questi due, un fallimento
                # rimesso a posto dalla riprova automatica resterebbe un
                # fallimento nel riepilogo, e la riprova non servirebbe a
                # niente se non a far girare due volte lo stesso lavoro.
                esito = (logs[0].status if logs else None)
                tentativi = max((getattr(l, "attempt_number", 1) or 1) for l in logs) if logs else 1
                return runs, ok, ko, dur, l_err, l_err_t, transferred, esito, tentativi

            def _fmt_last_run(dt) -> str:
                return dt.strftime("%d/%m %H:%M") if dt else "Mai"

            def _append(job, jtype, jtypes, **fields):
                nonlocal total_runs, successful, failed, total_duration
                runs, ok, ko, dur, l_err, l_err_t, transferred, esito, tentativi = _logs_24h(
                    job.id, jtypes
                )
                info = {
                    "id": job.id,
                    "name": job.name,
                    "type": jtype,
                    "notifica": getattr(job, "notify_mode", None) or "daily",
                    "in_ritardo": _in_ritardo(job),
                    "esito_finale": (job_logs[0].status if job_logs else None),
                    "tentativi_max": (
                        max((getattr(l, "attempt_number", 1) or 1) for l in job_logs)
                        if job_logs else 1
                    ),
                    "schedule": getattr(job, "schedule", None) or "Manuale",
                    "runs_24h": runs,
                    "success_24h": ok,
                    "failed_24h": ko,
                    "duration_24h": dur,
                    "last_transferred": transferred,
                    "last_error": l_err,
                    "last_error_time": l_err_t,
                    "esito_finale": esito,
                    "tentativi_max": tentativi,
                }
                info.update(fields)
                jobs_summary.append(info)
                total_runs += runs
                successful += ok
                failed += ko
                total_duration += dur

            node_by_id = {n.id: n for n in db.query(Node).all()}
            ep_by_id = {e.id: e for e in db.query(FileEndpoint).all()}

            for job in backup_pbs_jobs:
                src = node_by_id.get(job.source_node_id)
                pbs = node_by_id.get(getattr(job, "pbs_node_id", None))
                _append(
                    job, "backup", ["backup"],
                    vm_name=job.vm_name, vm_id=job.vm_id,
                    source_node=src.name if src else "N/A",
                    dest_node=pbs.name if pbs else "N/A",
                    source_dataset=f"vm/{job.vm_id}",
                    dest_dataset=getattr(job, "pbs_storage_id", None) or "PBS",
                    last_status=getattr(job, "last_status", None) or "never_run",
                    last_run=_fmt_last_run(getattr(job, "last_run", None)),
                )

            for job in host_backup_jobs:
                node = node_by_id.get(job.node_id)
                size = getattr(job, "last_backup_size", None)
                size_h = None
                if size:
                    for unit in ("B", "KB", "MB", "GB"):
                        if size < 1024 or unit == "GB":
                            size_h = f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
                            break
                        size = size / 1024
                _append(
                    job, "host_backup", ["host_backup"],
                    source_node=node.name if node else "N/A",
                    dest_node=node.name if node else "N/A",
                    source_dataset="configurazione host",
                    dest_dataset=job.dest_path,
                    last_status=getattr(job, "last_status", None) or "never_run",
                    last_run=_fmt_last_run(getattr(job, "last_run", None)),
                    last_transferred=size_h,
                )

            for job in migration_jobs_q:
                src = node_by_id.get(job.source_node_id)
                dst = node_by_id.get(getattr(job, "dest_node_id", None))
                _append(
                    job, "migration", ["migration"],
                    vm_name=job.vm_name, vm_id=job.vm_id,
                    source_node=src.name if src else "N/A",
                    dest_node=dst.name if dst else "N/A",
                    source_dataset=f"vm/{job.vm_id}",
                    dest_dataset=f"vm/{getattr(job, 'dest_vm_id', None) or job.vm_id}",
                    last_status=getattr(job, "last_status", None)
                    or getattr(job, "current_status", None) or "never_run",
                    last_run=_fmt_last_run(getattr(job, "last_run", None)),
                )

            for job in nas_sync_jobs_q:
                src = ep_by_id.get(job.source_endpoint_id)
                dst = ep_by_id.get(job.dest_endpoint_id)
                paths = ", ".join(job.source_paths or [])
                _append(
                    job, "nas_sync", ["nas_sync"],
                    source_node=src.name if src else "N/A",
                    dest_node=dst.name if dst else "N/A",
                    source_dataset=(paths[:60] + "…") if len(paths) > 60 else (paths or "—"),
                    dest_dataset=job.dest_base_path,
                    last_status=job.last_run_status or "never_run",
                    last_run=_fmt_last_run(job.last_run_at),
                )

            for job in vm_snapshot_jobs_q:
                run_state = job.run_state or {}
                results_n = len((run_state.get("results") or []))
                summary_rs = run_state.get("summary") or {}
                _append(
                    job, "vm_snapshot", ["vm_snapshot"],
                    source_node=f"{results_n} VM" if results_n else "—",
                    dest_node="snapshot Proxmox",
                    source_dataset=f"label {job.label}",
                    dest_dataset=f"keep {job.keep} — potati 24h: {summary_rs.get('pruned_total', '—')}",
                    last_status=job.last_run_status or "never_run",
                    last_run=_fmt_last_run(job.last_run_at),
                )

            # Il nome dell'impianto: la mail è una per installazione, e
            # nell'elenco della posta dev'essere chiaro quale.
            impianto = "DAPX"
            try:
                from database import SystemConfig
                riga = db.query(SystemConfig).filter(
                    SystemConfig.key == "cluster_name"
                ).first()
                if riga and (riga.value or "").strip():
                    impianto = riga.value.strip()
            except Exception as e:
                logger.debug(f"cluster_name non leggibile, uso il nome predefinito: {e}")

            summary_data = {
                "impianto": impianto,
                "total_jobs": sum(len(lst) for lst in all_job_lists),
                "total_runs": total_runs,
                "successful": successful,
                "failed": failed,
                "total_duration": total_duration,
                "jobs": jobs_summary
            }
            
        finally:
            db.close()
        
        results = {"sent": True, "channels": {}, "summary": summary_data}
        
        # Invia su tutti i canali
        # Email
        if config.smtp_enabled:
            try:
                self._configure_email_service(config)
                success, message = await asyncio.to_thread(self._send_daily_summary_email, summary_data)
                results["channels"]["email"] = {"success": success, "message": message}
            except Exception as e:
                logger.error(f"Errore invio email riepilogo: {e}")
                results["channels"]["email"] = {"success": False, "message": str(e)}
        
        # Webhook
        if config.webhook_enabled and config.webhook_url:
            try:
                webhook_result = await self._send_webhook(
                    config=config,
                    event_type="daily_summary",
                    data=summary_data
                )
                results["channels"]["webhook"] = webhook_result
            except Exception as e:
                results["channels"]["webhook"] = {"success": False, "message": str(e)}
        
        # Telegram
        if config.telegram_enabled and config.telegram_bot_token and config.telegram_chat_id:
            try:
                telegram_result = await self._send_telegram(
                    config=config,
                    message=self._format_telegram_summary(summary_data)
                )
                results["channels"]["telegram"] = telegram_result
            except Exception as e:
                results["channels"]["telegram"] = {"success": False, "message": str(e)}
        
        return results
    
    def _send_daily_summary_email(self, summary: Dict[str, Any]) -> Tuple[bool, str]:
        """Genera e invia il riepilogo giornaliero, raggruppato per tipologia.

        L'impaginazione sta in `notification_summary`: qui resta solo la
        spedizione. Prima erano 180 righe di HTML in mezzo alla logica, ed è
        il motivo per cui la tabella a sei colonne era sopravvissuta tanto —
        nessuno andava a toccarla per paura di rompere l'invio.
        """
        from services import notification_summary as riepilogo

        impianto = str(summary.get("impianto") or "DAPX")
        oggetto = riepilogo.oggetto_mail(summary, impianto=impianto)
        html = riepilogo.render_html(summary, impianto=impianto)
        testo = riepilogo.render_testo(summary, impianto=impianto)
        return email_service.send_email(oggetto, html, html=True, text_body=testo)

    async def _send_webhook(
        self,
        config: NotificationConfig,
        event_type: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Invia notifica via webhook"""
        try:
            from services.url_guard import assert_safe_webhook_url, UnsafeUrlError
            try:
                assert_safe_webhook_url(config.webhook_url)
            except UnsafeUrlError as guard_exc:
                logger.error(f"Webhook bloccato dal guard SSRF: {guard_exc}")
                return {"success": False, "message": f"URL webhook non sicuro: {guard_exc}"}

            from services.secrets import decrypt_secret
            headers = {"Content-Type": "application/json"}
            if config.webhook_secret:
                headers["X-Webhook-Secret"] = decrypt_secret(config.webhook_secret)
            
            payload = {
                "event": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "sanoid-manager"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    config.webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=15
                )
                
                if response.status_code < 300:
                    logger.info(f"Webhook inviato: {event_type}")
                    return {"success": True, "status_code": response.status_code}
                else:
                    logger.error(f"Webhook fallito: HTTP {response.status_code}")
                    return {"success": False, "status_code": response.status_code}
                    
        except Exception as e:
            logger.error(f"Errore webhook: {e}")
            return {"success": False, "message": str(e)}
    
    async def _send_telegram(
        self,
        config: NotificationConfig,
        message: str
    ) -> Dict[str, Any]:
        """Invia notifica via Telegram"""
        try:
            from services.secrets import decrypt_secret
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{decrypt_secret(config.telegram_bot_token)}/sendMessage",
                    json={
                        "chat_id": config.telegram_chat_id,
                        "text": message,
                        "parse_mode": "Markdown"
                    },
                    timeout=15
                )
                
                result = response.json()
                if result.get("ok"):
                    logger.info("Telegram notifica inviata")
                    return {"success": True}
                else:
                    logger.error(f"Telegram errore: {result.get('description')}")
                    return {"success": False, "message": result.get("description")}
                    
        except Exception as e:
            logger.error(f"Errore Telegram: {e}")
            return {"success": False, "message": str(e)}
    
    def _format_telegram_job_message(
        self,
        job_name: str,
        status: str,
        source: str,
        destination: str,
        duration: Optional[int],
        error: Optional[str]
    ) -> str:
        """Formatta messaggio Telegram per job"""
        emoji = {"success": "✅", "failed": "❌", "warning": "⚠️"}.get(status, "ℹ️")
        status_text = {"success": "Completato", "failed": "Fallito", "warning": "Attenzione"}.get(status, status)
        
        msg = f"""{emoji} *Replica {status_text}*

*Job:* {job_name}
*Sorgente:* `{source}`
*Destinazione:* `{destination}`"""
        
        if duration:
            minutes = duration // 60
            seconds = duration % 60
            msg += f"\n*Durata:* {minutes}m {seconds}s"
        
        if error:
            msg += f"\n\n❌ *Errore:*\n`{error[:500]}`"
        
        return msg
    
    def _format_telegram_summary(self, summary: Dict[str, Any]) -> str:
        """Riepilogo su Telegram: stessi gruppi della mail, solo ciò che non va.

        L'elenco completo di trenta job su Telegram non lo legge nessuno: si
        scorre e si perde il rosso in mezzo al verde.
        """
        from services import notification_summary as riepilogo

        return riepilogo.render_telegram(
            summary, impianto=str(summary.get("impianto") or "DAPX")
        )


# Singleton
notification_service = NotificationService()

