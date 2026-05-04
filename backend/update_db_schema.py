
import logging
from sqlalchemy import create_engine, text
from database import DATABASE_PATH

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _table_columns(conn, table: str) -> list[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return [r[1] for r in rows]


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

        trans = conn.begin()
        try:
            # --- nodes: host info cache ---
            _ensure_column(conn, "nodes", "host_info", "JSON")
            _ensure_column(conn, "nodes", "host_info_updated_at", "DATETIME")

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

            trans.commit()
        except Exception as e:
            trans.rollback()
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
