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


class NotificationService:
    """Servizio centralizzato per tutte le notifiche"""
    
    def __init__(self):
        self._config: Optional[NotificationConfig] = None
        self._last_config_load: Optional[datetime] = None
        self._config_cache_seconds = 60  # Ricarica config ogni 60 secondi
        # Tracking notifiche giornaliere per job: {job_id: last_notification_date}
        self._daily_job_notifications: Dict[int, datetime] = {}
    
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
    
    def _cleanup_old_notifications(self):
        """Rimuove tracking notifiche più vecchie di 2 giorni"""
        cutoff = datetime.utcnow() - timedelta(days=2)
        to_remove = [
            job_id for job_id, last_date in self._daily_job_notifications.items()
            if last_date < cutoff
        ]
        for job_id in to_remove:
            del self._daily_job_notifications[job_id]
    
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
        # Verifica notify_mode del job
        if notify_mode == "never":
            logger.debug(f"Notifiche disabilitate per job {job_name}")
            return {"sent": False, "reason": "notify_mode_never"}
        
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
        
        # Per notify_mode "daily": limita notifiche successo a 1 al giorno
        # Per notify_mode "always": notifica sempre
        # I fallimenti vengono sempre notificati (anche con notify_mode="daily")
        # La limitazione si applica sia per job schedulati che manuali
        if notify_mode == "daily" and job_id and status == "success":
            today = datetime.utcnow().date()
            # Chiave composita (job_type, job_id): job di tipo diverso con lo
            # stesso id numerico non si sopprimono più a vicenda (C-11/B6).
            dedupe_key = f"{job_type or 'job'}:{job_id}"
            last_notification = self._daily_job_notifications.get(dedupe_key)

            if last_notification and last_notification.date() == today:
                logger.debug(f"Notifica già inviata oggi per {dedupe_key}, skip (notify_mode=daily)")
                return {"sent": False, "reason": "daily_limit_reached"}

            # Aggiorna tracking
            self._daily_job_notifications[dedupe_key] = datetime.utcnow()
            
            # Pulizia entries vecchie (più di 2 giorni)
            self._cleanup_old_notifications()
        
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

        lines = []
        for g in overdue_groups:
            name = g.get("vm_name") or g.get("key") or "?"
            missed = g.get("missed_slots") or 0
            last = g.get("last_run") or "Mai"
            delay = g.get("hours_since_last_run")
            delay_txt = f"{delay:.1f}h" if delay is not None else "—"
            nxt = g.get("next_run") or "—"
            lines.append(
                f"• {name} (VMID {g.get('vm_id') or '—'}): "
                f"{missed} slot saltati, ritardo {delay_txt}, ultima run {last}, prossima {nxt}"
            )

        details = "\n".join(lines)
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
                return runs, ok, ko, dur, l_err, l_err_t, transferred

            def _fmt_last_run(dt) -> str:
                return dt.strftime("%d/%m %H:%M") if dt else "Mai"

            def _append(job, jtype, jtypes, **fields):
                nonlocal total_runs, successful, failed, total_duration
                runs, ok, ko, dur, l_err, l_err_t, transferred = _logs_24h(job.id, jtypes)
                info = {
                    "id": job.id,
                    "name": job.name,
                    "type": jtype,
                    "schedule": getattr(job, "schedule", None) or "Manuale",
                    "runs_24h": runs,
                    "success_24h": ok,
                    "failed_24h": ko,
                    "duration_24h": dur,
                    "last_transferred": transferred,
                    "last_error": l_err,
                    "last_error_time": l_err_t,
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

            summary_data = {
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
        """Genera e invia email riepilogo giornaliero con dettaglio per job"""
        
        # Determina stato generale
        if summary["failed"] > 0:
            status_emoji = "❌"
            status_color = "#dc3545"
            status_text = "Attenzione Richiesta"
        else:
            status_emoji = "✅"
            status_color = "#28a745"
            status_text = "Tutto OK"
        
        # Formatta durata totale
        hours = summary["total_duration"] // 3600
        minutes = (summary["total_duration"] % 3600) // 60
        duration_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        
        # Genera righe tabella per ogni job
        job_rows = ""
        for job in summary.get("jobs", []):
            # Determina colore stato
            if job["failed_24h"] > 0:
                status_icon = "❌"
                row_style = "background: #fff5f5;"
            elif job["last_status"] == "success":
                status_icon = "✅"
                row_style = ""
            elif job["last_status"] == "running":
                status_icon = "🔄"
                row_style = "background: #fff9e6;"
            elif job["last_status"] == "never_run":
                status_icon = "⏸️"
                row_style = "background: #f5f5f5;"
            else:
                status_icon = "⚠️"
                row_style = "background: #fff9e6;"
            
            # Formatta durata job
            job_hours = job["duration_24h"] // 3600
            job_mins = (job["duration_24h"] % 3600) // 60
            job_duration = f"{job_hours}h {job_mins}m" if job_hours > 0 else f"{job_mins}m"
            
            # Determina tipo job e formatta di conseguenza
            if job.get('type') == 'recovery':
                # Recovery Job: mostra VM, PBS, e durate fasi
                job_type_label = "🔄 Recovery (PBS)"
                vm_name = job.get('vm_name') or f"VM {job.get('vm_id', 'N/A')}"
                source_info = f"{job['source_node']}<br><span style='color: #6c757d; font-size: 10px;'><strong>{vm_name}</strong> (ID: {job.get('vm_id', 'N/A')})</span>"
                dest_info = f"{job['dest_node']}<br><span style='color: #6c757d; font-size: 10px;'>via {job.get('pbs_node', 'PBS')}</span>"
                
                # Durate fasi
                backup_mins = job.get('backup_duration_24h', 0) // 60
                backup_secs = job.get('backup_duration_24h', 0) % 60
                restore_mins = job.get('restore_duration_24h', 0) // 60
                restore_secs = job.get('restore_duration_24h', 0) % 60
                
                duration_info = f"""
                    <div style="font-size: 11px;">
                        <div>📦 Backup: <strong>{backup_mins}m {backup_secs}s</strong></div>
                        <div>🔄 Restore: <strong>{restore_mins}m {restore_secs}s</strong></div>
                    </div>
                """
            elif job.get("type") == "file_replication":
                job_type_label = "📁 Replica file (NAS)"
                source_info = (
                    f"{job['source_node']}<br>"
                    f"<code style='background: #f1f1f1; padding: 2px 4px; border-radius: 3px; font-size: 10px;'>"
                    f"{job.get('source_dataset', 'N/A')}</code>"
                )
                dest_info = (
                    f"{job['dest_node']}<br>"
                    f"<code style='background: #f1f1f1; padding: 2px 4px; border-radius: 3px; font-size: 10px;'>"
                    f"{job.get('dest_dataset', 'N/A')}</code>"
                )
                duration_info = f"""
                    {job_duration}<br>
                    <span style="color: #6c757d;">{job.get('last_transferred', '-')}</span>
                """
            else:
                _type_labels = {
                    "sync": "📦 Sync (ZFS/BTRFS)",
                    "backup": "💾 Backup (PBS)",
                    "migration": "🚀 Migration (Live)",
                    "nas_sync": "📁 Repliche dati (NAS)",
                    "vm_snapshot": "📸 Snapshot VM",
                    "host_backup": "🛡️ Host Backup",
                }
                job_type_label = _type_labels.get(job.get("type"), "📋 Job")
                vm_line = ""
                if job.get("vm_name") or job.get("vm_id"):
                    vm_label = job.get("vm_name") or f"VM {job.get('vm_id')}"
                    vm_id_part = f" (ID: {job['vm_id']})" if job.get("vm_id") else ""
                    vm_line = (
                        f"<span style='font-size: 11px;'><strong>{vm_label}</strong>{vm_id_part}</span><br>"
                    )
                source_info = f"{job['source_node']}<br>{vm_line}<code style='background: #f1f1f1; padding: 2px 4px; border-radius: 3px; font-size: 10px;'>{job.get('source_dataset', 'N/A')}</code>"
                dest_info = f"{job['dest_node']}<br><code style='background: #f1f1f1; padding: 2px 4px; border-radius: 3px; font-size: 10px;'>{job.get('dest_dataset', 'N/A')}</code>"
                duration_info = f"""
                    {job_duration}<br>
                    <span style="color: #6c757d;">{job.get('last_transferred', '-')}</span>
                """
            
            job_rows += f"""
            <tr style="{row_style}">
                <td style="padding: 12px; border-bottom: 1px solid #dee2e6;">
                    <strong>{job['name']}</strong><br>
                    <span style="font-size: 10px; color: #6c757d;">{job_type_label}</span><br>
                    <span style="font-size: 11px; color: #6c757d;">{job['schedule']}</span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #dee2e6; font-size: 12px;">
                    {source_info}
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #dee2e6; font-size: 12px;">
                    {dest_info}
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #dee2e6; text-align: center;">
                    <span style="font-size: 18px;">{status_icon}</span><br>
                    <span style="font-size: 11px; color: #6c757d;">{job['last_run']}</span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #dee2e6; text-align: center;">
                    <span style="color: #28a745; font-weight: bold;">{job['success_24h']}</span> / 
                    <span style="color: #dc3545; font-weight: bold;">{job['failed_24h']}</span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #dee2e6; text-align: center; font-size: 12px;">
                    {duration_info}
                </td>
            </tr>
            """
            
            # Aggiungi riga errore se presente
            if job["last_error"]:
                job_rows += f"""
                <tr style="background: #fff5f5;">
                    <td colspan="6" style="padding: 8px 12px; border-bottom: 2px solid #dee2e6; font-size: 11px;">
                        <span style="color: #dc3545;">⚠️ Ultimo errore ({job['last_error_time'] or 'N/A'}):</span>
                        <code style="display: block; margin-top: 4px; padding: 6px; background: #f8d7da; border-radius: 4px; white-space: pre-wrap; word-break: break-all;">{job['last_error']}</code>
                    </td>
                </tr>
                """
        
        subject = f"{status_emoji} Riepilogo Giornaliero - {summary['successful']}/{summary['total_runs']} esecuzioni OK"
        
        body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 900px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: {status_color}; color: white; padding: 25px; text-align: center; }}
        .header h1 {{ margin: 0 0 10px 0; font-size: 24px; }}
        .content {{ padding: 25px; }}
        .stats {{ display: flex; justify-content: space-around; margin: 20px 0; padding: 20px; background: #f8f9fa; border-radius: 8px; flex-wrap: wrap; }}
        .stat {{ text-align: center; min-width: 80px; margin: 5px; }}
        .stat-value {{ font-size: 28px; font-weight: bold; }}
        .stat-label {{ font-size: 11px; color: #6c757d; text-transform: uppercase; }}
        .stat-success {{ color: #28a745; }}
        .stat-failed {{ color: #dc3545; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 13px; }}
        th {{ background: #343a40; color: white; padding: 12px 8px; text-align: left; font-size: 11px; text-transform: uppercase; }}
        .footer {{ padding: 20px; text-align: center; color: #6c757d; font-size: 12px; border-top: 1px solid #dee2e6; }}
        code {{ font-family: 'Consolas', 'Monaco', monospace; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{status_emoji} Riepilogo Giornaliero DAPX-backandrepl</h1>
            <p>{status_text}</p>
        </div>
        
        <div class="content">
            <p><strong>Periodo:</strong> Ultime 24 ore | <strong>Data:</strong> {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC</p>
            
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{summary['total_jobs']}</div>
                    <div class="stat-label">Job Configurati</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{summary['total_runs']}</div>
                    <div class="stat-label">Esecuzioni</div>
                </div>
                <div class="stat">
                    <div class="stat-value stat-success">{summary['successful']}</div>
                    <div class="stat-label">Successi</div>
                </div>
                <div class="stat">
                    <div class="stat-value stat-failed">{summary['failed']}</div>
                    <div class="stat-label">Falliti</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{duration_str}</div>
                    <div class="stat-label">Tempo Totale</div>
                </div>
            </div>
            
            <h3 style="margin-top: 30px; color: #343a40;">📋 Dettaglio Job</h3>
            
            <table>
                <thead>
                    <tr>
                        <th>Job</th>
                        <th>Sorgente</th>
                        <th>Destinazione</th>
                        <th>Stato</th>
                        <th>24h (OK/Fail)</th>
                        <th>Durata/Transfer</th>
                    </tr>
                </thead>
                <tbody>
                    {job_rows if job_rows else '<tr><td colspan="6" style="padding: 20px; text-align: center; color: #6c757d;">Nessun job configurato</td></tr>'}
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>Questo riepilogo è stato generato automaticamente da DAPX-backandrepl.</p>
        </div>
    </div>
</body>
</html>
"""
        
        return email_service.send_email(subject, body, html=True)
    
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
        """Formatta messaggio Telegram per riepilogo giornaliero con dettaglio per job"""
        
        if summary["failed"] > 0:
            emoji = "❌"
            status = "Attenzione Richiesta"
        else:
            emoji = "✅"
            status = "Tutto OK"
        
        hours = summary["total_duration"] // 3600
        minutes = (summary["total_duration"] % 3600) // 60
        
        msg = f"""{emoji} *Riepilogo Giornaliero DAPX-backandrepl*

*Stato:* {status}
*Periodo:* Ultime 24 ore

📊 *Statistiche Generali:*
• Job Configurati: {summary['total_jobs']}
• Esecuzioni: {summary['total_runs']}
• ✅ Successi: {summary['successful']}
• ❌ Falliti: {summary['failed']}
• ⏱ Tempo Totale: {hours}h {minutes}m"""
        
        # Dettaglio per job
        jobs = summary.get("jobs", [])
        if jobs:
            msg += "\n\n📋 *Dettaglio Job:*"
            for job in jobs[:10]:  # Max 10 job nel messaggio Telegram
                if job["failed_24h"] > 0:
                    job_emoji = "❌"
                elif job["last_status"] == "success":
                    job_emoji = "✅"
                elif job["last_status"] == "never_run":
                    job_emoji = "⏸️"
                else:
                    job_emoji = "⚠️"
                
                msg += f"\n\n{job_emoji} *{job['name']}*"
                if job.get("vm_name") or job.get("vm_id"):
                    vm_label = job.get("vm_name") or "VM"
                    msg += f"\n   {vm_label} (ID: {job.get('vm_id', '?')})"
                msg += f"\n   `{job['source_node']}` → `{job['dest_node']}`"
                msg += f"\n   24h: {job['success_24h']}✓ {job['failed_24h']}✗ | Ultimo: {job['last_run']}"
                
                if job["last_error"]:
                    msg += f"\n   ⚠️ Errore: `{job['last_error'][:100]}...`"
        
        return msg


# Singleton
notification_service = NotificationService()

