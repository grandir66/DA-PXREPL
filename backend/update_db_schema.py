
import logging
from sqlalchemy import create_engine, text
from database import Base, DATABASE_PATH

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Parole «umane» che le prime versioni della UI salvavano al posto di un cron.
# Lo scheduler le scarta a ogni avvio («Cron non valido 'daily'») e il job non
# parte MAI — senza fallire, quindi senza che nessuno se ne accorga (DTS,
# 2026-09-13: tre backup config fermi da luglio). L'indice scagliona i
# giornalieri di dieci minuti, come i job creati a mano l'8 settembre.
_PAROLE_LEGACY = {
    "daily": lambda i: f"{(i * 10) % 60} 1 * * *",
    "weekly": lambda i: "0 1 * * 0",
    "hourly": lambda i: "0 * * * *",
}


def cron_da_parola(schedule, indice: int = 0):
    """Il cron equivalente a una parola legacy; None se non è una di quelle."""
    if not schedule:
        return None
    parola = str(schedule).strip().lower()
    regola = _PAROLE_LEGACY.get(parola)
    return regola(indice) if regola else None


def migra_schedule_legacy(conn, tabella: str = "host_backup_jobs") -> int:
    """Sostituisce le parole legacy con un cron vero. Ritorna quante righe."""
    if tabella not in _tables(conn) or "schedule" not in _table_columns(conn, tabella):
        return 0
    righe = conn.execute(text(
        f"SELECT id, schedule FROM {tabella} WHERE schedule IS NOT NULL ORDER BY id"
    )).fetchall()
    cambiati = 0
    for riga in righe:
        cron = cron_da_parola(riga[1], cambiati)
        if cron is None:
            continue
        conn.execute(
            text(f"UPDATE {tabella} SET schedule = :cron WHERE id = :id"),
            {"cron": cron, "id": riga[0]},
        )
        logger.info("%s #%s: pianificazione '%s' → '%s'", tabella, riga[0], riga[1], cron)
        cambiati += 1
    return cambiati


def _table_columns(conn, table: str) -> list[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return [r[1] for r in rows]


def _tables(conn) -> list[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    return [r[0] for r in rows]


def _ensure_column(conn, table: str, column: str, ddl_type: str) -> None:
    """Idempotente: aggiunge la colonna solo se non esiste già."""
    try:
        cols = _table_columns(conn, table)
    except Exception as e:
        logger.debug(f"Tabella {table} non leggibile ancora: {e}")
        return
    if not cols:
        # Tabella inesistente: create_all la creerà al primo avvio.
        return
    if column in cols:
        return
    logger.info(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
    except Exception as e:
        logger.error(f"Errore aggiunta colonna {table}.{column}: {e}")


def update_schema():
    """Esegue le migrazioni leggere idempotenti.

    Tutto e' wrappato in una BEGIN/COMMIT per evitare di lasciare lo
    schema in stato inconsistente in caso di crash a meta'. SQLite non
    supporta DDL transazionale completo (alcune ALTER non rollback)
    ma `PRAGMA foreign_keys=OFF` + BEGIN ci mette al sicuro per le
    ADD COLUMN che usiamo qui.
    """
    logger.info(f"Updating database schema at {DATABASE_PATH}")
    engine = create_engine(f"sqlite:///{DATABASE_PATH}")

    with engine.connect() as conn:
        # SQLite: foreign keys off durante migrazione per non bloccare le
        # ADD COLUMN su tabelle con FK.
        try:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
        except Exception:
            pass

        # SQLAlchemy 2.x: engine.connect() ha autobegin, niente
        # conn.begin() esplicito. Si committa/rollback direttamente
        # via conn.
        try:
            # --- nodes: host info cache ---
            _ensure_column(conn, "nodes", "host_info", "JSON")
            _ensure_column(conn, "nodes", "host_info_updated_at", "DATETIME")

            # trigger_source: distingue run schedulati da manuali (NON è il FK triggered_by).
            _ensure_column(conn, "job_logs", "trigger_source", "VARCHAR(20)")

            # --- schedule_config: struttura JSON "human" accanto al cron raw.
            for table in (
                "sync_jobs",
                "backup_jobs",
                "recovery_jobs",
                "host_backup_jobs",
            ):
                _ensure_column(conn, table, "schedule_config", "JSON")

            # current_status su sync_jobs (allineato a backup_jobs/recovery_jobs).
            _ensure_column(conn, "sync_jobs", "current_status", "VARCHAR(20)")

            # Override registrazione VM (3.16.5): bridge/VLAN/nome destinazione.
            _ensure_column(conn, "sync_jobs", "dest_vm_name", "VARCHAR(100)")
            _ensure_column(conn, "sync_jobs", "dest_bridge", "VARCHAR(50)")
            _ensure_column(conn, "sync_jobs", "dest_vlan", "INTEGER")

            # Parametri sync_method=pve_native (3.17.0): vzdump+scp+qmrestore
            # senza dipendenza da ZFS/BTRFS/PBS.
            _ensure_column(conn, "sync_jobs", "dump_dir", "VARCHAR(255)")
            _ensure_column(conn, "sync_jobs", "bandwidth_limit_kb", "INTEGER")
            _ensure_column(conn, "sync_jobs", "pve_compress", "VARCHAR(10)")
            _ensure_column(conn, "sync_jobs", "cleanup_after", "BOOLEAN")
            _ensure_column(conn, "sync_jobs", "replace_existing", "BOOLEAN")
            _ensure_column(conn, "sync_jobs", "force_cpu_host", "BOOLEAN")

            _ensure_column(conn, "recovery_jobs", "notify_on_each_run", "BOOLEAN")
            _ensure_column(conn, "backup_jobs", "notify_on_each_run", "BOOLEAN")

            # Repliche dati v2: tabella nuova, creata idempotente via metadata.
            # Il modello è registrato importando services.nas_sync.models.
            from services.nas_sync import models as _nas_sync_models  # noqa: F401
            # Snapshot VM: stessa meccanica di registrazione.
            from services.vm_snapshot import models as _vm_snapshot_models  # noqa: F401
            Base.metadata.create_all(bind=engine)

            # P-07: indici sui percorsi caldi di job_logs (lista per job, stats per
            # finestra temporale). Idempotenti.
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_joblog_type_job_started "
                "ON job_logs (job_type, job_id, started_at)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_joblog_started_status "
                "ON job_logs (started_at, status)"
            ))

            # Riprova: da «15 minuti, 3 tentativi» a «60 minuti, 1 tentativo».
            # SOLO per chi è rimasto ai vecchi valori predefiniti: chi ha
            # scelto a mano un'attesa diversa se la tiene. Una UPDATE secca
            # cancellerebbe quella scelta senza dirlo a nessuno.
            for tabella in ("sync_jobs", "recovery_jobs"):
                if tabella not in _tables(conn):
                    continue
                colonne = _table_columns(conn, tabella)
                if "retry_delay_minutes" not in colonne or "max_retries" not in colonne:
                    continue
                esito = conn.execute(text(
                    f"UPDATE {tabella} SET retry_delay_minutes = 60, max_retries = 1 "
                    "WHERE retry_delay_minutes = 15 AND max_retries = 3"
                ))
                if esito.rowcount:
                    logger.info(
                        "Riprova portata a 60 min / 1 tentativo su %s job di %s",
                        esito.rowcount, tabella,
                    )

            migra_schedule_legacy(conn)

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Migration rolled back: {e}")
            raise
        finally:
            try:
                conn.execute(text("PRAGMA foreign_keys=ON"))
            except Exception:
                pass

    logger.info("Schema update completed")


def cleanup_old_logs(days_jobs: int = 30, days_audit: int = 90) -> dict:
    """Elimina JobLog piu' vecchi di `days_jobs` e AuditLog piu' vecchi
    di `days_audit`. Idempotente; chiamato dallo scheduler giornalmente.
    Ritorna {jobs_deleted, audits_deleted}.
    """
    from datetime import datetime, timedelta
    engine = create_engine(f"sqlite:///{DATABASE_PATH}")
    counts = {"jobs_deleted": 0, "audits_deleted": 0}
    with engine.connect() as conn:
        try:
            cutoff_jobs = (datetime.utcnow() - timedelta(days=days_jobs)).isoformat()
            r = conn.execute(
                text("DELETE FROM job_logs WHERE started_at < :c"),
                {"c": cutoff_jobs},
            )
            counts["jobs_deleted"] = r.rowcount or 0
        except Exception as e:
            logger.warning(f"cleanup job_logs: {e}")
        try:
            cutoff_audit = (datetime.utcnow() - timedelta(days=days_audit)).isoformat()
            r = conn.execute(
                text("DELETE FROM audit_logs WHERE timestamp < :c"),
                {"c": cutoff_audit},
            )
            counts["audits_deleted"] = r.rowcount or 0
        except Exception as e:
            logger.warning(f"cleanup audit_logs: {e}")
        try:
            conn.commit()
        except Exception:
            pass
    return counts


if __name__ == "__main__":
    update_schema()
