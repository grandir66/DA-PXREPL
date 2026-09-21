"""
Scheduler Service - Gestione job schedulati
Con supporto notifiche e riepilogo giornaliero
"""

import asyncio
import os
from datetime import datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, Callable
import logging
from croniter import croniter
from sqlalchemy.orm import Session

from database import SessionLocal, SyncJob, JobLog, Node, NotificationConfig, SystemConfig, HostBackupJob, MigrationJob, FileReplicationJob, BackupJob, RecoveryJob
from services.notification_service import notification_service
from services.host_backup_service import host_backup_service
from services.host_info_service import host_info_service
from services.cache_service import cache_service

logger = logging.getLogger(__name__)

# Finestra (secondi) dopo l'inizio di uno slot cron in cui un restart può
# ancora innescare la run di quello slot (evita backlog di settimane).
_CRON_SLOT_GRACE_SEC = 120

# Quante volte ritentare il riepilogo giornaliero se nessun canale lo accetta.
# I tentativi cadono a un minuto l'uno dall'altro (il giro dello scheduler) e
# stanno dentro la finestra dell'ora, quindi coprono un SMTP che torna su da
# solo senza martellarlo per sessanta minuti.
_MAX_TENTATIVI_RIEPILOGO = 5

# Timezone in cui interpretare le espressioni cron dei job schedulati.
# Default Europe/Rome (ORA LOCALE, come si aspetta l'utente). Storage e
# confronti interni restano in UTC naive; solo la valutazione del cron è locale.
_SCHEDULER_TZ_NAME = os.environ.get("DAPX_SCHEDULER_TZ", "Europe/Rome")
try:
    _SCHEDULER_TZ = ZoneInfo(_SCHEDULER_TZ_NAME)
except Exception:  # zoneinfo mancante o nome errato → fallback UTC (comportamento legacy)
    _SCHEDULER_TZ = ZoneInfo("UTC")


def _next_run_after(schedule: str, after_utc: datetime) -> datetime:
    """Prossimo fire del cron DOPO `after_utc` (naive UTC), interpretando la
    stringa cron in ora locale (_SCHEDULER_TZ). Ritorna un naive UTC."""
    base_local = after_utc.replace(tzinfo=timezone.utc).astimezone(_SCHEDULER_TZ)
    nxt = croniter(schedule, base_local).get_next(datetime)  # aware, ora locale
    return nxt.astimezone(timezone.utc).replace(tzinfo=None)


def _prev_run_before(schedule: str, before_utc: datetime) -> datetime:
    """Slot cron PRECEDENTE (o corrente) rispetto a `before_utc`, in ora locale.
    Ritorna un naive UTC."""
    base_local = before_utc.replace(tzinfo=timezone.utc).astimezone(_SCHEDULER_TZ)
    prev = croniter(schedule, base_local).get_prev(datetime)
    return prev.astimezone(timezone.utc).replace(tzinfo=None)


def compute_initial_next_run(
    schedule: str,
    last_run: Optional[datetime],
    now: datetime,
) -> datetime:
    """Calcola la prossima esecuzione senza sparare tutti i cron arretrati al restart.
    Il cron è valutato in ora locale (_SCHEDULER_TZ); i confronti restano in UTC naive.

    - Se siamo entro _CRON_SLOT_GRACE_SEC dall'inizio dello slot corrente e
      last_run è anteriore allo slot → slot corrente (run appena iniziata).
    - Altrimenti → prossimo slot futuro (niente catch-up multi-giorno/settimana).
    """
    try:
        next_future = _next_run_after(schedule, now)
        prev_slot = _prev_run_before(schedule, now)
    except Exception as exc:
        # Cron non valido (es. numero di campi errato): NON rilanciare a ogni
        # tick (spam log). "Parcheggia" il job lontano e logga una volta sola.
        logger.warning("Cron non valido %r: job non schedulato finché non corretto (%s)", schedule, exc)
        return now + timedelta(days=3650)
    if (last_run is None or last_run < prev_slot) and (now - prev_slot).total_seconds() <= _CRON_SLOT_GRACE_SEC:
        return prev_slot
    return next_future


def _riepilogo_consegnato(result: dict) -> Optional[bool]:
    """Il riepilogo è arrivato a qualcuno?

    Tre risposte, non due, ed è la ragione per cui questa funzione esiste:

    * ``True``  — almeno un canale l'ha accettato: giornata fatta.
    * ``False`` — si è provato e nessun canale l'ha preso (SMTP giù, token
      Telegram scaduto): vale la pena ritentare.
    * ``None``  — non c'era niente da mandare (notifiche non configurate,
      nessun canale acceso, nessun job): ritentare non cambierebbe nulla.

    `send_daily_summary` mette ``sent: True`` appena decide di provarci; se
    l'invio poi fallisce lo dice solo dentro ``channels``. Leggere il primo e
    non i secondi è esattamente l'errore che faceva perdere il riepilogo.
    """
    if not result.get("sent"):
        return None
    canali = result.get("channels") or {}
    if not canali:
        return None
    return any(bool(c.get("success")) for c in canali.values())


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
        # Tentativi di invio del riepilogo nella giornata corrente: un SMTP
        # che non risponde alle 8:00 non deve costare l'intero riepilogo.
        self._tentativi_riepilogo: int = 0
        # Riprove in attesa: {job_key: {'quando','job_id','tentativo'}}.
        # In memoria di proposito: una riprova è un rimedio a un guasto
        # passeggero, e se il servizio si riavvia il guasto passeggero non
        # c'è più — al prossimo slot cron il job riparte comunque.
        self._riprove: Dict[str, Dict[str, Any]] = {}
        self._last_vm_cache_refresh: Optional[datetime] = None
        self._daily_summary_hour: int = 8  # Ora predefinita: 08:00 UTC
        self._daily_summary_enabled: bool = True
        # Vita del loop (3.24.0, dopo nove ore di silenzio su dts-repl il
        # 21/09: un check bloccato su un SSH aveva fermato tutto, e nessuno
        # lo vedeva). `last_tick` è l'ultimo giro completo; `_scadenze` conta,
        # per check, quante volte di fila ha superato il suo tetto.
        self.last_tick: Optional[datetime] = None
        self._scadenze: Dict[str, int] = {}
        self._ultimo_avviso_check: Dict[str, datetime] = {}

    async def start(self):
        """Avvia lo scheduler"""
        if self._running:
            return

        # Pulizia di job rimasti in stato `running` da un crash precedente.
        # Senza questo step un crash del backend lascia per sempre i job
        # come "in esecuzione" e impedisce nuove run.
        self._reset_stale_running_jobs()

        self._running = True
        self.last_tick = datetime.utcnow()
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
        from database import RecoveryJob, BackupJob, HostBackupJob  # lazy import per evitare cicli
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
            # C-10/B12: anche HostBackupJob può restare 'running' dopo un crash.
            for hj in db.query(HostBackupJob).filter(
                HostBackupJob.current_status == "running"
            ).all():
                hj.current_status = "failed"
                hj.last_status = "failed"
                hj.last_error = stale_msg
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
        from services.sync_job_reconciliation import reconcile_sync_jobs_after_restart
        await reconcile_sync_jobs_after_restart()

    async def _reconcile_stuck_sync_jobs(self) -> None:
        """Ogni ~2 min chiude job al 100% senza processi attivi o riavvia monitor."""
        now = datetime.utcnow()
        last = getattr(self, "_last_sync_reconcile", None)
        if last and (now - last).total_seconds() < 120:
            return
        self._last_sync_reconcile = now
        try:
            from services.sync_job_reconciliation import (
                _reconcile_running_sync_jobs_once,
                reconcile_pending_vm_registrations,
            )
            await _reconcile_running_sync_jobs_once()
            await reconcile_pending_vm_registrations()
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
    
    # I check di ogni giro, con il tetto in secondi oltre il quale si passa
    # al successivo. I tetti sono larghi (un giro di cache su cinque nodi puo'
    # durare minuti): servono a non morire, non a fare in fretta.
    CHECKS = (
        ("jobs", "_check_and_run_jobs", 120),
        ("riprove", "_check_riprove", 120),
        ("riepilogo", "_check_daily_summary", 180),
        ("in_ritardo", "_check_replication_overdue", 120),
        ("uuid_duplicati", "_check_uuid_duplicati", 300),
        ("host_info", "_check_host_info_updates", 600),
        ("cache_vm", "_refresh_vm_cache", 600),
        ("pulizia_log", "_daily_log_cleanup", 300),
        ("job_bloccati", "_reconcile_stuck_sync_jobs", 300),
    )
    STALE_DOPO_S = 600          # /api/health: oltre dieci minuti senza giro, «stale»
    AVVISO_CHECK_COOLDOWN_S = 24 * 3600

    async def _scheduler_loop(self):
        """Loop principale dello scheduler.

        Ogni check ha un tetto (`CHECKS`): se non finisce si logga, si conta e
        si passa oltre — un SSH che non torna non ferma le repliche degli
        altri (dts-repl, 21/09/2026: fermo dalle 15:52 per nove ore dentro
        `update_host_details`, senza una riga di log). A fine giro il battito.
        """
        while self._running:
            for nome, metodo, tetto in self.CHECKS:
                if not self._running:
                    break
                await self._esegui_check(nome, metodo, tetto)
            self._battito()
            await asyncio.sleep(60)  # Check ogni minuto

    async def _esegui_check(self, nome: str, metodo: str, tetto: int) -> bool:
        """Un check col suo tetto. Ritorna True se ha finito in tempo."""
        try:
            await asyncio.wait_for(getattr(self, metodo)(), timeout=tetto)
            self._scadenze[nome] = 0
            return True
        except asyncio.TimeoutError:
            n = self._scadenze.get(nome, 0) + 1
            self._scadenze[nome] = n
            logger.error(
                "Scheduler: il check %s non ha finito in %ss (%s di fila): passo oltre",
                nome, tetto, n,
            )
            if n >= 2:
                await self._avvisa_check_bloccato(nome, tetto, n)
            return False
        except Exception as e:
            logger.error(f"Errore nello scheduler ({nome}): {e}")
            return False

    def _battito(self) -> None:
        """Il giro e' finito: lo si scrive in memoria e nel DB (per /api/health
        dopo un riavvio e per chi legge il DB). Non alza mai."""
        adesso = datetime.utcnow()
        self.last_tick = adesso
        try:
            db = SessionLocal()
            try:
                cfg = db.query(SystemConfig).filter(SystemConfig.key == "scheduler_last_tick").first()
                if cfg:
                    cfg.value = adesso.isoformat()
                else:
                    db.add(SystemConfig(key="scheduler_last_tick", value=adesso.isoformat()))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.debug("Battito dello scheduler non scritto nel DB: %s", e)

    def stale_da_secondi(self, adesso: Optional[datetime] = None) -> Optional[float]:
        """Secondi dall'ultimo giro completo; None se il loop non e' partito."""
        if self.last_tick is None:
            return None
        return ((adesso or datetime.utcnow()) - self.last_tick).total_seconds()

    async def _avvisa_check_bloccato(self, nome: str, tetto: int, volte: int) -> None:
        """Warning sul canale delle notifiche, al massimo uno al giorno per check."""
        adesso = datetime.utcnow()
        ultimo = self._ultimo_avviso_check.get(nome)
        if ultimo and (adesso - ultimo).total_seconds() < self.AVVISO_CHECK_COOLDOWN_S:
            return
        try:
            esito = await notification_service.send_job_notification(
                job_name=f"Scheduler: check «{nome}» bloccato",
                status="warning",
                source="Scheduler DAPX",
                destination="—",
                details=(
                    f"Il check «{nome}» non finisce entro {tetto} s da {volte} giri di fila. "
                    "Gli altri check proseguono, ma qualcosa (di solito un nodo che non risponde "
                    "via SSH) lo tiene fermo: guardare il journal e i nodi."
                ),
                is_scheduled=True,
                notify_mode="always",
                job_type="sync",
            )
            if esito.get("sent"):
                self._ultimo_avviso_check[nome] = adesso
        except Exception as e:
            logger.debug("Avviso check bloccato non inviato: %s", e)

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
            
            # Invia riepilogo.
            #
            # La giornata si segna «fatta» SOLO se almeno un canale ha davvero
            # accettato il messaggio. Prima la si segnava comunque, e siccome
            # `send_daily_summary` restituisce `sent: True` anche quando il
            # canale email fallisce (l'esito vero sta in `channels`), un SMTP
            # irraggiungibile alle 8:00 costava il riepilogo dell'intera
            # giornata, in silenzio. Dall'8 settembre 2026 è l'unico messaggio
            # che arriva quando tutto va come deve — i job non mandano più
            # posta per conto loro — quindi perderlo vuol dire non sapere
            # niente per 24 ore.
            logger.info("Invio riepilogo giornaliero...")
            try:
                result = await notification_service.send_daily_summary()
                consegnato = _riepilogo_consegnato(result)
            except Exception as e:
                logger.error(f"Errore invio riepilogo giornaliero: {e}")
                consegnato = False

            if consegnato is False:
                self._tentativi_riepilogo += 1
                if self._tentativi_riepilogo < _MAX_TENTATIVI_RIEPILOGO:
                    logger.warning(
                        "Riepilogo giornaliero non consegnato (tentativo %s/%s): "
                        "riprovo al prossimo giro",
                        self._tentativi_riepilogo, _MAX_TENTATIVI_RIEPILOGO,
                    )
                    return
                logger.error(
                    "Riepilogo giornaliero non consegnato dopo %s tentativi: "
                    "oggi nessuno saprà com'è andata. Controllare SMTP/webhook/Telegram.",
                    _MAX_TENTATIVI_RIEPILOGO,
                )
            elif consegnato:
                logger.info(f"Riepilogo giornaliero inviato: {result.get('channels', {})}")
            else:
                logger.debug(f"Riepilogo non inviato: {result.get('reason')}")

            self._tentativi_riepilogo = 0
            self._last_daily_summary = now

    async def _check_replication_overdue(self):
        """Alert proattivo se VM/gruppi schedulati non hanno rispettato lo slot cron."""
        now = datetime.utcnow()
        if getattr(self, "_last_overdue_check", None):
            if (now - self._last_overdue_check).total_seconds() < 3600:
                return
        self._last_overdue_check = now

        db = SessionLocal()
        try:
            from services.replication_health_service import (
                build_replication_health_report,
                OVERDUE_ALERT_COOLDOWN_HOURS,
            )

            jobs = db.query(SyncJob).filter(SyncJob.is_active == True).all()
            report = build_replication_health_report(jobs, now=now)
            if report.get("overdue_group_count", 0) == 0:
                return

            last_alert_cfg = db.query(SystemConfig).filter(
                SystemConfig.key == "replication_overdue_last_alert"
            ).first()
            keys_cfg = db.query(SystemConfig).filter(
                SystemConfig.key == "replication_overdue_last_alert_keys"
            ).first()
            chiavi = sorted(str(g.get("key")) for g in (report.get("overdue_groups") or []))
            gia_avvisate = set((keys_cfg.value or "").split(",")) if keys_cfg and keys_cfg.value else set()
            nuove = [k for k in chiavi if k not in gia_avvisate]
            if last_alert_cfg and last_alert_cfg.value and not nuove:
                # Stessi gruppi dell'ultima mail: si ripete una volta al
                # giorno, non ogni sei ore. Un gruppo NUOVO in ritardo invece
                # si segnala subito, cooldown o no.
                try:
                    last_alert = datetime.fromisoformat(last_alert_cfg.value)
                    if (now - last_alert).total_seconds() < OVERDUE_ALERT_COOLDOWN_HOURS * 3600:
                        return
                except ValueError:
                    pass

            logger.info(
                "Replica in ritardo: %s gruppi — invio alert",
                report["overdue_group_count"],
            )
            result = await notification_service.send_replication_overdue_alert(
                report.get("overdue_groups") or []
            )
            if not result.get("sent"):
                logger.debug("Alert replica in ritardo non inviato: %s", result.get("reason"))
                return

            if last_alert_cfg:
                last_alert_cfg.value = now.isoformat()
            else:
                db.add(SystemConfig(key="replication_overdue_last_alert", value=now.isoformat()))
            if keys_cfg:
                keys_cfg.value = ",".join(chiavi)
            else:
                db.add(SystemConfig(key="replication_overdue_last_alert_keys", value=",".join(chiavi)))
            db.commit()
            logger.info("Alert replica in ritardo inviato: %s", result.get("channels", {}))
        except Exception as e:
            logger.error(f"Errore check replica in ritardo: {e}")
        finally:
            db.close()

    async def _check_uuid_duplicati(self):
        """Alert se due VM di un cluster portano lo stesso `smbios1 uuid` (ogni 6 h).

        Incidente DTS 2026-09-21: repliche con l'uuid della sorgente, Veeam
        escludeva la produzione dal backup e nessuno lo vedeva. Stesso
        canale e stessa cadenza di «replica in ritardo»: una volta al giorno
        per le stesse coppie, subito per una coppia nuova.
        """
        now = datetime.utcnow()
        ultimo = getattr(self, "_last_uuid_dup_check", None)
        if ultimo and (now - ultimo).total_seconds() < 6 * 3600:
            return
        self._last_uuid_dup_check = now

        db = SessionLocal()
        try:
            from services.ssh_service import ssh_service
            from services.uuid_duplicati import (
                raccogli_smbios, trova_uuid_duplicati, chiavi_duplicati,
            )
            from services.replication_health_service import OVERDUE_ALERT_COOLDOWN_HOURS

            nodi = db.query(Node).filter(
                Node.is_active == True,  # noqa: E712
                Node.node_type == "pve",
            ).all()
            if not nodi:
                return
            righe, muti = await raccogli_smbios(ssh_service, nodi)
            if muti:
                logger.debug("uuid duplicati: nodi senza risposta %s", ", ".join(muti))
            duplicati = trova_uuid_duplicati(righe)
            if not duplicati:
                return

            last_alert_cfg = db.query(SystemConfig).filter(
                SystemConfig.key == "uuid_duplicati_last_alert"
            ).first()
            keys_cfg = db.query(SystemConfig).filter(
                SystemConfig.key == "uuid_duplicati_last_alert_keys"
            ).first()
            chiavi = chiavi_duplicati(duplicati)
            gia_avvisate = set((keys_cfg.value or "").split(",")) if keys_cfg and keys_cfg.value else set()
            nuove = [k for k in chiavi if k not in gia_avvisate]
            if last_alert_cfg and last_alert_cfg.value and not nuove:
                try:
                    last_alert = datetime.fromisoformat(last_alert_cfg.value)
                    if (now - last_alert).total_seconds() < OVERDUE_ALERT_COOLDOWN_HOURS * 3600:
                        return
                except ValueError:
                    pass

            logger.warning("UUID SMBIOS duplicati: %s coppie — invio alert", len(duplicati))
            result = await notification_service.send_uuid_duplicati_alert(duplicati)
            if not result.get("sent"):
                logger.debug("Alert uuid duplicati non inviato: %s", result.get("reason"))
                return

            if last_alert_cfg:
                last_alert_cfg.value = now.isoformat()
            else:
                db.add(SystemConfig(key="uuid_duplicati_last_alert", value=now.isoformat()))
            if keys_cfg:
                keys_cfg.value = ",".join(chiavi)
            else:
                db.add(SystemConfig(key="uuid_duplicati_last_alert_keys", value=",".join(chiavi)))
            db.commit()
            logger.info("Alert uuid duplicati inviato: %s", result.get("channels", {}))
        except Exception as e:
            logger.error(f"Errore check uuid duplicati: {e}")
        finally:
            db.close()

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
    
    async def _guarded_execute_sync_job(
        self, job_key: str, job_id: int, tentativo: int = 1
    ) -> None:
        """Esegue un SyncJob standalone; mantiene il lock se la replica continua in background."""
        from services.sync_job_execution import execute_sync_job_task

        keep_lock = False
        try:
            keep_lock = await execute_sync_job_task(job_id, tentativo=tentativo)
        except Exception as e:
            logger.error(f"SyncJob {job_id} fallito: {e}", exc_info=True)
        finally:
            if not keep_lock:
                self._unlock(job_key)
                # Il lock è rilasciato: la replica è finita davvero e il suo
                # esito è nel database. Se è andata male, si riprova fra un'ora.
                self._valuta_riprova(job_key, job_id, tentativo)

    def _valuta_riprova(self, job_key: str, job_id: int, tentativo: int) -> None:
        """Registra una riprova se la replica è fallita e ne ha ancora diritto.

        `retry_on_failure`, `max_retries` e `retry_delay_minutes` stanno nel
        database di ogni job **dal primo giorno** e nessun servizio di
        esecuzione li leggeva: configurazione promessa dalle API e mai
        applicata (scoperto il 2026-09-08). Adesso li legge questo.

        Una replica non si dichiara fallita al primo colpo: `syncoid` cade
        anche per un `dataset is busy` o uno snapshot ancora in corso, cose
        che un'ora dopo non ci sono più. Fallita è quella che non passa
        **nemmeno alla riprova**.
        """
        db = SessionLocal()
        try:
            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if not job:
                return
            if (job.last_status or "").lower() != "failed":
                self._riprove.pop(job_key, None)
                return
            if not getattr(job, "retry_on_failure", False):
                logger.info("SyncJob %s fallito, riprova disattivata sul job", job_id)
                return
            massimo = int(getattr(job, "max_retries", 0) or 0)
            if tentativo > massimo:
                logger.error(
                    "SyncJob %s (%s) fallito anche al tentativo %s di %s: è un guasto",
                    job_id, job.name, tentativo, massimo + 1,
                )
                self._riprove.pop(job_key, None)
                return
            attesa = int(getattr(job, "retry_delay_minutes", 0) or 60)
            quando = datetime.utcnow() + timedelta(minutes=attesa)
            self._riprove[job_key] = {
                "quando": quando, "job_id": job_id, "tentativo": tentativo + 1,
            }
            logger.warning(
                "SyncJob %s (%s) fallito al tentativo %s: riprova alle %s",
                job_id, job.name, tentativo, quando.strftime("%H:%M"),
            )
        except Exception as e:  # noqa: BLE001 — non deve fermare lo scheduler
            logger.error("Valutazione riprova per SyncJob %s fallita: %s", job_id, e)
        finally:
            db.close()

    async def _check_riprove(self) -> None:
        """Fa partire le riprove scadute. Una per giro, come i job normali."""
        if not self._riprove:
            return
        now = datetime.utcnow()
        for job_key, r in list(self._riprove.items()):
            if now < r["quando"]:
                continue
            self._riprove.pop(job_key, None)
            if not self._try_lock(job_key):
                # Sta già girando (lo slot cron è arrivato prima della riprova):
                # non serve riprovare quel che è già in corso.
                logger.info("Riprova di %s saltata: il job è già in esecuzione", job_key)
                continue
            logger.info("Riprova %s: tentativo %s", job_key, r["tentativo"])
            asyncio.create_task(
                self._guarded_execute_sync_job(job_key, r["job_id"], r["tentativo"])
            )

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
                        group_members = [
                            sj for sj in sync_jobs if sj.vm_group_id == job.vm_group_id
                        ]
                        group_last_run = max(
                            (sj.last_run for sj in group_members if sj.last_run),
                            default=None,
                        )
                        if group_key not in self._jobs:
                            self._jobs[group_key] = compute_initial_next_run(
                                job.schedule, group_last_run, now
                            )
                        next_run = self._jobs[group_key]
                        if now >= next_run:
                            disk_busy = any(
                                (sj.last_status or "").lower() in ("running", "started")
                                for sj in group_members
                            )
                            if disk_busy:
                                logger.info(
                                    f"VM group {job.vm_group_id}: disco in running, "
                                    f"slot cron rinviato"
                                )
                            elif self._try_lock(group_key):
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
                                self._jobs[group_key] = _next_run_after(job.schedule, now)
                                for sj in group_members:
                                    self._jobs[f"sync_{sj.id}"] = self._jobs[group_key]
                            else:
                                logger.info(
                                    f"VM group {job.vm_group_id} ancora in esecuzione: skip"
                                )
                        continue

                    job_key = f"sync_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run, now
                        )

                    next_run = self._jobs[job_key]

                    if now >= next_run:
                        disk_busy = (job.last_status or "").lower() in (
                            "running",
                            "started",
                        )
                        if disk_busy:
                            logger.info(
                                f"SyncJob {job.id} in running su DB, slot cron rinviato"
                            )
                        elif self._try_lock(job_key):
                            logger.info(
                                f"Esecuzione SyncJob schedulato: {job.name} (ID: {job.id})"
                            )
                            asyncio.create_task(
                                self._guarded_execute_sync_job(job_key, job.id)
                            )
                            self._jobs[job_key] = _next_run_after(job.schedule, now)
                        else:
                            logger.info(
                                f"SyncJob {job.id} ancora in esecuzione: skip fire schedulato"
                            )

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
                            self._jobs[job_key] = _next_run_after(job.schedule, now)
                        else:
                            logger.info(f"HostBackupJob {job.id} ancora in esecuzione: skip fire schedulato")
                        
                except Exception as e:
                    logger.error(f"Errore scheduling HostBackupJob {job.id}: {e}")

            # === FILE REPLICATION JOBS ===
            file_replication_jobs = db.query(FileReplicationJob).filter(
                FileReplicationJob.is_active == True,
                FileReplicationJob.schedule.isnot(None),
                FileReplicationJob.schedule != "",
            ).all()

            for job in file_replication_jobs:
                try:
                    job_key = f"file_replication_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run_at, now
                        )

                    next_run = self._jobs[job_key]

                    if now >= next_run:
                        if self._try_lock(job_key):
                            logger.info(
                                f"Esecuzione FileReplicationJob schedulato: {job.name} (ID: {job.id})"
                            )
                            asyncio.create_task(
                                self._guarded_execute(
                                    job_key,
                                    self._execute_file_replication_job,
                                    job.id,
                                )
                            )
                            self._jobs[job_key] = _next_run_after(job.schedule, now)
                        else:
                            logger.info(
                                f"FileReplicationJob {job.id} ancora in esecuzione: skip fire schedulato"
                            )

                    # Persisti il prossimo run nel DB così l'UI può mostrarlo
                    if job.next_run_at != self._jobs[job_key]:
                        job.next_run_at = self._jobs[job_key]
                        db.commit()
                except Exception as e:
                    logger.error(f"Errore scheduling FileReplicationJob {job.id}: {e}")

            # === NAS SYNC JOBS (Repliche dati v2) ===
            from services.nas_sync.models import NasSyncJob

            nas_sync_jobs_q = db.query(NasSyncJob).filter(
                NasSyncJob.is_active == True,
                NasSyncJob.schedule.isnot(None),
                NasSyncJob.schedule != "",
            ).all()

            for job in nas_sync_jobs_q:
                try:
                    job_key = f"nas_sync_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run_at, now
                        )
                    next_run = self._jobs[job_key]
                    if now >= next_run:
                        if self._try_lock(job_key):
                            logger.info(
                                f"Esecuzione NasSyncJob schedulato: {job.name} (ID: {job.id})"
                            )
                            asyncio.create_task(
                                self._guarded_execute(
                                    job_key,
                                    self._execute_nas_sync_job,
                                    job.id,
                                )
                            )
                            self._jobs[job_key] = _next_run_after(job.schedule, now)
                        else:
                            logger.info(
                                f"NasSyncJob {job.id} ancora in esecuzione: skip fire schedulato"
                            )
                    # Persisti il prossimo run nel DB così l'UI può mostrarlo
                    if job.next_run_at != self._jobs[job_key]:
                        job.next_run_at = self._jobs[job_key]
                        db.commit()
                except Exception as e:
                    logger.error(f"Errore scheduling NasSyncJob {job.id}: {e}")

            # === VM SNAPSHOT JOBS (Snapshot VM) ===
            from services.vm_snapshot.models import VmSnapshotJob

            vm_snapshot_jobs_q = db.query(VmSnapshotJob).filter(
                VmSnapshotJob.is_active == True,
                VmSnapshotJob.schedule.isnot(None),
                VmSnapshotJob.schedule != "",
            ).all()

            for job in vm_snapshot_jobs_q:
                try:
                    job_key = f"vm_snapshot_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run_at, now
                        )
                    next_run = self._jobs[job_key]
                    if now >= next_run:
                        if self._try_lock(job_key):
                            logger.info(
                                f"Esecuzione VmSnapshotJob schedulato: {job.name} (ID: {job.id})"
                            )
                            asyncio.create_task(
                                self._guarded_execute(
                                    job_key,
                                    self._execute_vm_snapshot_job,
                                    job.id,
                                )
                            )
                            self._jobs[job_key] = _next_run_after(job.schedule, now)
                        else:
                            logger.info(
                                f"VmSnapshotJob {job.id} ancora in esecuzione: skip fire schedulato"
                            )
                except Exception as e:
                    logger.error(f"Errore scheduling VmSnapshotJob {job.id}: {e}")

            # === BACKUP PBS JOBS ===
            backup_jobs = db.query(BackupJob).filter(
                BackupJob.is_active == True,
                BackupJob.schedule.isnot(None),
                BackupJob.schedule != "",
            ).all()

            for job in backup_jobs:
                try:
                    job_key = f"backup_pbs_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run, now
                        )

                    next_run = self._jobs[job_key]

                    if now >= next_run:
                        busy = (job.current_status or "").lower() in ("running",)
                        if busy:
                            logger.info(
                                f"BackupJob {job.id} in esecuzione, slot cron rinviato"
                            )
                        elif self._try_lock(job_key):
                            logger.info(
                                f"Esecuzione BackupJob schedulato: {job.name} (ID: {job.id})"
                            )
                            asyncio.create_task(
                                self._guarded_execute(
                                    job_key,
                                    self._execute_backup_pbs_job,
                                    job.id,
                                )
                            )
                            self._jobs[job_key] = _next_run_after(job.schedule, now)
                        else:
                            logger.info(
                                f"BackupJob {job.id} ancora in esecuzione: skip fire schedulato"
                            )
                except Exception as e:
                    logger.error(f"Errore scheduling BackupJob {job.id}: {e}")

            # === RECOVERY PBS JOBS (replica via PBS) ===
            recovery_jobs = db.query(RecoveryJob).filter(
                RecoveryJob.is_active == True,
                RecoveryJob.schedule.isnot(None),
                RecoveryJob.schedule != "",
            ).all()

            for job in recovery_jobs:
                try:
                    job_key = f"recovery_pbs_{job.id}"
                    if job_key not in self._jobs:
                        self._jobs[job_key] = compute_initial_next_run(
                            job.schedule, job.last_run, now
                        )

                    next_run = self._jobs[job_key]

                    if now >= next_run:
                        busy = (job.current_status or "").lower() in (
                            "backing_up",
                            "restoring",
                            "registering",
                            "running",
                        )
                        if busy:
                            logger.info(
                                f"RecoveryJob {job.id} in esecuzione, slot cron rinviato"
                            )
                        elif self._try_lock(job_key):
                            logger.info(
                                f"Esecuzione RecoveryJob schedulato: {job.name} (ID: {job.id})"
                            )
                            asyncio.create_task(
                                self._guarded_execute(
                                    job_key,
                                    self._execute_recovery_pbs_job,
                                    job.id,
                                )
                            )
                            self._jobs[job_key] = _next_run_after(job.schedule, now)
                        else:
                            logger.info(
                                f"RecoveryJob {job.id} ancora in esecuzione: skip fire schedulato"
                            )
                except Exception as e:
                    logger.error(f"Errore scheduling RecoveryJob {job.id}: {e}")
            
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
                            self._jobs[job_key] = _next_run_after(job.schedule, now)
                        else:
                            logger.info(f"MigrationJob {job.id} ancora in esecuzione: skip fire schedulato")
                        
                except Exception as e:
                    logger.error(f"Errore scheduling MigrationJob {job.id}: {e}")
                    
        finally:
            db.close()
    
    async def _execute_vm_group_sync(self, vm_group_id: str):
        """Esegue in sequenza tutti i dischi di un gruppo VM."""
        from services.vm_group_sync_service import execute_vm_group_sync_task
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
                from services.host_backup_service import notify_host_backup_result
                await notify_host_backup_result(
                    job, node, status="success", duration=duration,
                    backup_name=result.get('backup_name'),
                    size_human=result.get('size_human'), is_scheduled=True,
                )
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
                from services.host_backup_service import notify_host_backup_result
                await notify_host_backup_result(
                    job, node, status="failed", duration=duration,
                    error=result.get('error'), is_scheduled=True,
                )

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
            # C-10/B12: senza questo il job resta 'running' per sempre dopo un crash.
            try:
                job = db.query(HostBackupJob).filter(HostBackupJob.id == job_id).first()
                if job:
                    job.current_status = "failed"
                    job.last_status = "failed"
                    job.last_error = str(e)[:1000]
                    job.error_count = (job.error_count or 0) + 1
            except Exception:
                pass
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

    async def _execute_file_replication_job(self, job_id: int):
        """Esegue un job replica file schedulato."""
        from services.file_replication.file_replication_execution import execute_file_replication_job

        await execute_file_replication_job(job_id, triggered_by="scheduled")

    async def _execute_nas_sync_job(self, job_id: int):
        """Esegue un job Repliche dati v2 schedulato."""
        from services.nas_sync.execution import execute_nas_sync_job

        await execute_nas_sync_job(job_id, triggered_by="scheduled")

    async def _execute_vm_snapshot_job(self, job_id: int):
        """Esegue un job Snapshot VM schedulato."""
        from services.vm_snapshot.execution import execute_vm_snapshot_job

        await execute_vm_snapshot_job(job_id, is_scheduled=True)

    async def _execute_backup_pbs_job(self, job_id: int):
        """Esegue un backup VM verso PBS schedulato."""
        from routers.backup_jobs import execute_backup_task

        await execute_backup_task(job_id, "")

    async def _execute_recovery_pbs_job(self, job_id: int):
        """Esegue una replica via PBS schedulata (backup + restore)."""
        from services.recovery_job_execution import execute_recovery_job_task

        await execute_recovery_job_task(job_id, triggered_by=None)
    
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

    def update_file_replication_schedule(
        self,
        job_id: int,
        schedule: str,
        last_run: Optional[datetime] = None,
    ) -> None:
        key = f"file_replication_{job_id}"
        if schedule:
            self._jobs[key] = compute_initial_next_run(schedule, last_run, datetime.utcnow())
        elif key in self._jobs:
            del self._jobs[key]

    def remove_file_replication_schedule(self, job_id: int) -> None:
        self._jobs.pop(f"file_replication_{job_id}", None)

    def update_nas_sync_schedule(
        self,
        job_id: int,
        schedule: str,
        last_run: Optional[datetime] = None,
    ) -> None:
        key = f"nas_sync_{job_id}"
        if schedule:
            self._jobs[key] = compute_initial_next_run(schedule, last_run, datetime.utcnow())
        elif key in self._jobs:
            del self._jobs[key]

    def remove_nas_sync_schedule(self, job_id: int) -> None:
        self._jobs.pop(f"nas_sync_{job_id}", None)

    def next_run_for(self, job_key: str) -> Optional[datetime]:
        """Prossima esecuzione pianificata per una chiave job (dal registry live).

        Usato dalle API per esporre next_run senza scrivere il DB a ogni tick (B7)."""
        return self._jobs.get(job_key)

    def update_vm_snapshot_schedule(
        self,
        job_id: int,
        schedule: str,
        last_run: Optional[datetime] = None,
    ) -> None:
        key = f"vm_snapshot_{job_id}"
        if schedule:
            self._jobs[key] = compute_initial_next_run(schedule, last_run, datetime.utcnow())
        elif key in self._jobs:
            del self._jobs[key]

    def remove_vm_snapshot_schedule(self, job_id: int) -> None:
        self._jobs.pop(f"vm_snapshot_{job_id}", None)

    def update_backup_pbs_schedule(
        self,
        job_id: int,
        schedule: str,
        last_run: Optional[datetime] = None,
    ) -> None:
        key = f"backup_pbs_{job_id}"
        if schedule:
            self._jobs[key] = compute_initial_next_run(schedule, last_run, datetime.utcnow())
        elif key in self._jobs:
            del self._jobs[key]

    def remove_backup_pbs_schedule(self, job_id: int) -> None:
        self._jobs.pop(f"backup_pbs_{job_id}", None)

    def update_recovery_pbs_schedule(
        self,
        job_id: int,
        schedule: str,
        last_run: Optional[datetime] = None,
    ) -> None:
        key = f"recovery_pbs_{job_id}"
        if schedule:
            self._jobs[key] = compute_initial_next_run(schedule, last_run, datetime.utcnow())
        elif key in self._jobs:
            del self._jobs[key]

    def remove_recovery_pbs_schedule(self, job_id: int) -> None:
        self._jobs.pop(f"recovery_pbs_{job_id}", None)


# Singleton
scheduler_service = SchedulerService()
