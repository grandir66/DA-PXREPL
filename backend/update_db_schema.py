
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
    logger.info(f"Updating database schema at {DATABASE_PATH}")
    engine = create_engine(f"sqlite:///{DATABASE_PATH}")

    with engine.connect() as conn:
        # --- nodes: host info cache ---
        _ensure_column(conn, "nodes", "host_info", "JSON")
        _ensure_column(conn, "nodes", "host_info_updated_at", "DATETIME")

        # --- schedule_config: struttura JSON "human" accanto al cron raw.
        # Aggiunta su tutti i job che hanno un campo `schedule`. Il backend
        # continua a usare `schedule` (cron) per APScheduler/croniter; la UI
        # legge/scrive `schedule_config` per editing senza tornare al cron
        # crudo.
        for table in (
            "sync_jobs",
            "backup_jobs",
            "recovery_jobs",
            "host_backup_jobs",
        ):
            _ensure_column(conn, table, "schedule_config", "JSON")

        try:
            conn.commit()
        except Exception:
            pass

    logger.info("Schema update completed")


if __name__ == "__main__":
    update_schema()
