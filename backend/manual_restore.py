
import os
import sys
import asyncio
import tarfile
import json
import shutil
import logging
from datetime import datetime

# Configurazione base
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ManualRestore")

# Percorsi (adattati per installazione standard)
INSTALL_DIR = "/opt/dapx-unified"
DATA_DIR = "/var/lib/dapx-unified"
CONFIG_DIR = "/etc/dapx-unified"
SSH_DIR = "/root/.ssh"

async def restore_backup(backup_path):
    if not os.path.exists(backup_path):
        logger.error(f"File non trovato: {backup_path}")
        return

    logger.info(f"Avvio ripristino da: {backup_path}")
    
    extract_dir = os.path.join(tempfile.mkdtemp(), "extracted")
    
    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(extract_dir)
            
        manifest_path = os.path.join(extract_dir, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            logger.info(f"Backup info: Host={manifest.get('hostname')}, Ver={manifest.get('version')}")
        
        # 1. Database
        db_src = os.path.join(extract_dir, "database", "dapx.db")
        if os.path.exists(db_src):
            db_dest = os.path.join(DATA_DIR, "dapx.db")
            if os.path.exists(db_dest):
                shutil.copy2(db_dest, f"{db_dest}.bak")
            os.makedirs(os.path.dirname(db_dest), exist_ok=True)
            shutil.copy2(db_src, db_dest)
            logger.info("Database ripristinato")

        # 2. SSH Keys
        ssh_src = os.path.join(extract_dir, "ssh")
        if os.path.exists(ssh_src):
            os.makedirs(SSH_DIR, exist_ok=True)
            for f in os.listdir(ssh_src):
                src = os.path.join(ssh_src, f)
                dest = os.path.join(SSH_DIR, f)
                shutil.copy2(src, dest)
                if f in ["id_rsa", "id_ed25519"]:
                    os.chmod(dest, 0o600)
            logger.info("Chiavi SSH ripristinate")
            
        # 3. Config & Certs
        # (Semplificato per manual restore)
        
        logger.info("Ripristino completato con successo!")
        
    except Exception as e:
        logger.error(f"Errore: {e}")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 manual_restore.py <path_to_backup.tar.gz>")
        sys.exit(1)
        
    import tempfile
    asyncio.run(restore_backup(sys.argv[1]))
