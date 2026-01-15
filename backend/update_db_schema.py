
import logging
from sqlalchemy import create_engine, text
from database import DATABASE_PATH

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_schema():
    logger.info(f"Updating database schema at {DATABASE_PATH}")
    engine = create_engine(f"sqlite:///{DATABASE_PATH}")
    
    with engine.connect() as conn:
        # Check if columns exist
        result = conn.execute(text("PRAGMA table_info(nodes)"))
        columns = [row[1] for row in result.fetchall()]
        
        if "host_info" not in columns:
            logger.info("Adding column 'host_info' to table 'nodes'")
            try:
                conn.execute(text("ALTER TABLE nodes ADD COLUMN host_info JSON"))
                logger.info("Column 'host_info' added successfully")
            except Exception as e:
                logger.error(f"Error adding column 'host_info': {e}")

        if "host_info_updated_at" not in columns:
            logger.info("Adding column 'host_info_updated_at' to table 'nodes'")
            try:
                conn.execute(text("ALTER TABLE nodes ADD COLUMN host_info_updated_at DATETIME"))
                logger.info("Column 'host_info_updated_at' added successfully")
            except Exception as e:
                logger.error(f"Error adding column 'host_info_updated_at': {e}")
                
    logger.info("Schema update completed")

if __name__ == "__main__":
    update_schema()
