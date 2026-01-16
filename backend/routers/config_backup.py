"""
DAPX-Unified - Configuration Backup & Restore
Export/Import completo di configurazione, database, chiavi SSH e certificati
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import json
import shutil
import tarfile
import tempfile
import logging
from datetime import datetime
import hashlib
import base64

from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from routers.auth import require_admin, User

router = APIRouter(prefix="/api/config-backup", tags=["Configuration Backup"])
logger = logging.getLogger(__name__)

# Configurazione percorsi
INSTALL_DIR = os.environ.get("DAPX_INSTALL_DIR", "/opt/dapx-unified")
DATA_DIR = os.environ.get("DAPX_DATA_DIR", "/var/lib/dapx-unified")
CONFIG_DIR = os.environ.get("DAPX_CONFIG_DIR", "/etc/dapx-unified")
SSH_DIR = "/root/.ssh"

# Per sviluppo locale (Mac)
if not os.path.exists(DATA_DIR):
    DATA_DIR = os.path.expanduser("~/.dapx-unified")
if not os.path.exists(CONFIG_DIR):
    CONFIG_DIR = os.path.expanduser("~/.dapx-unified/config")
if not os.path.exists(SSH_DIR):
    SSH_DIR = os.path.expanduser("~/.ssh")


class BackupInfo(BaseModel):
    filename: str
    created_at: str
    size: int
    includes_database: bool
    includes_ssh_keys: bool
    includes_certificates: bool
    includes_config: bool
    version: str
    source_hostname: str


class RestoreResult(BaseModel):
    success: bool
    message: str
    restored_items: List[str]
    warnings: List[str]


def get_version() -> str:
    """Ottieni versione corrente"""
    version_file = os.path.join(INSTALL_DIR, "version.json")
    if os.path.exists(version_file):
        try:
            with open(version_file) as f:
                data = json.load(f)
                return data.get("version", "unknown")
        except:
            pass
    return "unknown"


def get_hostname() -> str:
    """Ottieni hostname corrente"""
    import socket
    return socket.gethostname()


@router.get("/available")
async def list_available_backups(user: User = Depends(require_admin)) -> List[BackupInfo]:
    """Lista backup disponibili localmente"""
    backup_dir = os.path.join(DATA_DIR, "backups")
    backups = []
    
    if os.path.exists(backup_dir):
        for filename in os.listdir(backup_dir):
            if filename.endswith(".dapx-backup.tar.gz"):
                filepath = os.path.join(backup_dir, filename)
                try:
                    # Estrai metadata dal backup
                    with tarfile.open(filepath, "r:gz") as tar:
                        # Cerca manifest.json
                        try:
                            manifest_file = tar.extractfile("manifest.json")
                            if manifest_file:
                                manifest = json.load(manifest_file)
                                backups.append(BackupInfo(
                                    filename=filename,
                                    created_at=manifest.get("created_at", ""),
                                    size=os.path.getsize(filepath),
                                    includes_database=manifest.get("includes_database", False),
                                    includes_ssh_keys=manifest.get("includes_ssh_keys", False),
                                    includes_certificates=manifest.get("includes_certificates", False),
                                    includes_config=manifest.get("includes_config", False),
                                    version=manifest.get("version", "unknown"),
                                    source_hostname=manifest.get("hostname", "unknown")
                                ))
                        except:
                            # Backup senza manifest
                            backups.append(BackupInfo(
                                filename=filename,
                                created_at=datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
                                size=os.path.getsize(filepath),
                                includes_database=True,
                                includes_ssh_keys=False,
                                includes_certificates=False,
                                includes_config=False,
                                version="unknown",
                                source_hostname="unknown"
                            ))
                except Exception as e:
                    logger.warning(f"Errore lettura backup {filename}: {e}")
    
    return sorted(backups, key=lambda x: x.created_at, reverse=True)


@router.post("/export")
async def create_backup(
    include_database: bool = True,
    include_ssh_keys: bool = True,
    include_certificates: bool = True,
    include_config: bool = True,
    user: User = Depends(require_admin)
):
    """Crea backup completo e restituisce file per download"""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"dapx-backup-{timestamp}.dapx-backup.tar.gz"
    
    # Directory temporanea per preparare il backup
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_content_dir = os.path.join(temp_dir, "dapx-backup")
        os.makedirs(backup_content_dir)
        
        manifest = {
            "version": get_version(),
            "created_at": datetime.now().isoformat(),
            "hostname": get_hostname(),
            "includes_database": include_database,
            "includes_ssh_keys": include_ssh_keys,
            "includes_certificates": include_certificates,
            "includes_config": include_config,
            "files": []
        }
        
        # 1. Database
        if include_database:
            db_path = os.path.join(DATA_DIR, "dapx.db")
            if os.path.exists(db_path):
                db_dest = os.path.join(backup_content_dir, "database")
                os.makedirs(db_dest, exist_ok=True)
                shutil.copy2(db_path, os.path.join(db_dest, "dapx.db"))
                manifest["files"].append("database/dapx.db")
                logger.info("Database incluso nel backup")
        
        # 2. Chiavi SSH
        if include_ssh_keys:
            ssh_dest = os.path.join(backup_content_dir, "ssh")
            os.makedirs(ssh_dest, exist_ok=True)
            
            ssh_files = ["id_rsa", "id_rsa.pub", "id_ed25519", "id_ed25519.pub", "known_hosts", "authorized_keys"]
            for ssh_file in ssh_files:
                src = os.path.join(SSH_DIR, ssh_file)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(ssh_dest, ssh_file))
                    manifest["files"].append(f"ssh/{ssh_file}")
            
            logger.info("Chiavi SSH incluse nel backup")
        
        # 3. Certificati
        if include_certificates:
            cert_dest = os.path.join(backup_content_dir, "certificates")
            os.makedirs(cert_dest, exist_ok=True)
            
            # Cerca certificati in varie posizioni
            cert_paths = [
                os.path.join(CONFIG_DIR, "ssl"),
                os.path.join(INSTALL_DIR, "ssl"),
                "/etc/ssl/dapx-unified"
            ]
            
            for cert_dir in cert_paths:
                if os.path.exists(cert_dir):
                    for cert_file in os.listdir(cert_dir):
                        if cert_file.endswith(('.pem', '.crt', '.key', '.p12')):
                            src = os.path.join(cert_dir, cert_file)
                            shutil.copy2(src, os.path.join(cert_dest, cert_file))
                            manifest["files"].append(f"certificates/{cert_file}")
            
            logger.info("Certificati inclusi nel backup")
        
        # 4. File di configurazione
        if include_config:
            config_dest = os.path.join(backup_content_dir, "config")
            os.makedirs(config_dest, exist_ok=True)
            
            # File .env
            env_file = os.path.join(CONFIG_DIR, "dapx-unified.env")
            if os.path.exists(env_file):
                shutil.copy2(env_file, os.path.join(config_dest, "dapx-unified.env"))
                manifest["files"].append("config/dapx-unified.env")
            
            # version.json
            version_file = os.path.join(INSTALL_DIR, "version.json")
            if os.path.exists(version_file):
                shutil.copy2(version_file, os.path.join(config_dest, "version.json"))
                manifest["files"].append("config/version.json")
            
            logger.info("Configurazione inclusa nel backup")
        
        # Salva manifest
        with open(os.path.join(backup_content_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
        
        # Crea archivio
        backup_dir = os.path.join(DATA_DIR, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, backup_name)
        
        with tarfile.open(backup_path, "w:gz") as tar:
            for item in os.listdir(backup_content_dir):
                tar.add(
                    os.path.join(backup_content_dir, item),
                    arcname=item
                )
        
        logger.info(f"Backup creato: {backup_path}")
        
        return {
            "success": True,
            "filename": backup_name,
            "size": os.path.getsize(backup_path),
            "path": backup_path,
            "download_url": f"/api/config-backup/download/{backup_name}"
        }


from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query
from routers.auth import get_current_user, User

# ...

from fastapi import Request

@router.get("/download/{filename}")
async def download_backup(
    request: Request,
    filename: str, 
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Scarica un file di backup (supporta Auth Header o Query Param)"""
    
    from routers.auth import get_current_user_from_query, get_current_user
    from services.auth_service import auth_service
    
    user = None
    
    # 1. Prova Query Param
    if token:
        try:
            user = await get_current_user_from_query(token, db)
        except HTTPException:
            pass
        
    # 2. Prova Header Authorization
    if not user:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            bearer_token = auth_header.split(" ")[1]
            success, payload = auth_service.verify_token(bearer_token)
            if success and payload:
                user_id = payload.get("sub")
                user = db.query(User).filter(User.id == int(user_id)).first()

    if not user:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    
    if user.role != "admin":
         raise HTTPException(status_code=403, detail="Richiesto ruolo admin")

    
    if user.role != "admin":
         raise HTTPException(status_code=403, detail="Richiesto ruolo admin")
    
    # Valida nome file
    if not filename.endswith(".dapx-backup.tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    backup_path = os.path.join(DATA_DIR, "backups", filename)
    
    logger.info(f"Download backup da: {backup_path}")
    
    if not os.path.exists(backup_path):
        logger.error(f"Backup non trovato: {backup_path}")
        raise HTTPException(status_code=404, detail="Backup non trovato")
    
    return FileResponse(
        backup_path,
        media_type="application/gzip",
        filename=filename
    )




@router.post("/import")
async def restore_backup(
    file: UploadFile = File(...),
    restore_database: bool = True,
    restore_ssh_keys: bool = True,
    restore_certificates: bool = True,
    restore_config: bool = True,
    user: User = Depends(require_admin)
) -> RestoreResult:
    """Importa un backup da file caricato"""
    
    if not file.filename.endswith((".tar.gz", ".dapx-backup.tar.gz")):
        raise HTTPException(status_code=400, detail="File deve essere un archivio .tar.gz")
    
    warnings = []
    restored_items = []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Salva file caricato
        temp_file = os.path.join(temp_dir, "upload.tar.gz")
        with open(temp_file, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Estrai archivio
        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir)
        
        try:
            with tarfile.open(temp_file, "r:gz") as tar:
                tar.extractall(extract_dir)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Errore estrazione archivio: {e}")
        
        # Leggi manifest
        manifest_path = os.path.join(extract_dir, "manifest.json")
        manifest = {}
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            logger.info(f"Ripristino backup da {manifest.get('hostname', 'unknown')} v{manifest.get('version', 'unknown')}")
        
        # 1. Ripristina Database
        if restore_database:
            db_src = os.path.join(extract_dir, "database", "dapx.db")
            if os.path.exists(db_src):
                db_dest = os.path.join(DATA_DIR, "dapx.db")
                
                # Backup database esistente
                if os.path.exists(db_dest):
                    backup_existing = f"{db_dest}.pre-restore-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    shutil.copy2(db_dest, backup_existing)
                    warnings.append(f"Database esistente salvato in {backup_existing}")
                
                os.makedirs(os.path.dirname(db_dest), exist_ok=True)
                shutil.copy2(db_src, db_dest)
                restored_items.append("Database")
                logger.info("Database ripristinato")
            else:
                warnings.append("Database non trovato nel backup")
        
        # 2. Ripristina Chiavi SSH
        if restore_ssh_keys:
            ssh_src = os.path.join(extract_dir, "ssh")
            if os.path.exists(ssh_src):
                os.makedirs(SSH_DIR, exist_ok=True)
                
                for ssh_file in os.listdir(ssh_src):
                    src = os.path.join(ssh_src, ssh_file)
                    dest = os.path.join(SSH_DIR, ssh_file)
                    
                    # Backup esistente
                    if os.path.exists(dest):
                        backup_existing = f"{dest}.pre-restore"
                        shutil.copy2(dest, backup_existing)
                    
                    shutil.copy2(src, dest)
                    
                    # Imposta permessi corretti
                    if ssh_file in ["id_rsa", "id_ed25519"]:
                        os.chmod(dest, 0o600)
                    elif ssh_file.endswith(".pub"):
                        os.chmod(dest, 0o644)
                
                restored_items.append("Chiavi SSH")
                logger.info("Chiavi SSH ripristinate")
            else:
                warnings.append("Chiavi SSH non trovate nel backup")
        
        # 3. Ripristina Certificati
        if restore_certificates:
            cert_src = os.path.join(extract_dir, "certificates")
            if os.path.exists(cert_src) and os.listdir(cert_src):
                cert_dest = os.path.join(CONFIG_DIR, "ssl")
                os.makedirs(cert_dest, exist_ok=True)
                
                for cert_file in os.listdir(cert_src):
                    src = os.path.join(cert_src, cert_file)
                    dest = os.path.join(cert_dest, cert_file)
                    shutil.copy2(src, dest)
                    
                    # Permessi appropriati per chiavi private
                    if cert_file.endswith(".key"):
                        os.chmod(dest, 0o600)
                
                restored_items.append("Certificati")
                logger.info("Certificati ripristinati")
            else:
                warnings.append("Certificati non trovati nel backup")
        
        # 4. Ripristina Configurazione
        if restore_config:
            config_src = os.path.join(extract_dir, "config")
            if os.path.exists(config_src):
                os.makedirs(CONFIG_DIR, exist_ok=True)
                
                env_src = os.path.join(config_src, "dapx-unified.env")
                if os.path.exists(env_src):
                    env_dest = os.path.join(CONFIG_DIR, "dapx-unified.env")
                    if os.path.exists(env_dest):
                        shutil.copy2(env_dest, f"{env_dest}.pre-restore")
                    shutil.copy2(env_src, env_dest)
                
                restored_items.append("Configurazione")
                logger.info("Configurazione ripristinata")
            else:
                warnings.append("Configurazione non trovata nel backup")
    
    return RestoreResult(
        success=True,
        message=f"Ripristino completato. Riavvia il servizio per applicare le modifiche.",
        restored_items=restored_items,
        warnings=warnings
    )


@router.delete("/delete/{filename}")
async def delete_backup(filename: str, user: User = Depends(require_admin)):
    """Elimina un backup"""
    
    if not filename.endswith(".dapx-backup.tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    backup_path = os.path.join(DATA_DIR, "backups", filename)
    
    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup non trovato")
    
    os.remove(backup_path)
    logger.info(f"Backup eliminato: {filename}")
    
    return {"success": True, "message": f"Backup {filename} eliminato"}


@router.get("/info")
async def get_backup_info(user: User = Depends(require_admin)):
    """Info sui dati che verranno inclusi nel backup"""
    
    info = {
        "database": {
            "exists": os.path.exists(os.path.join(DATA_DIR, "dapx.db")),
            "path": os.path.join(DATA_DIR, "dapx.db"),
            "size": 0
        },
        "ssh_keys": {
            "exists": False,
            "files": []
        },
        "certificates": {
            "exists": False,
            "files": []
        },
        "config": {
            "exists": os.path.exists(os.path.join(CONFIG_DIR, "dapx-unified.env")),
            "path": CONFIG_DIR
        },
        "version": get_version(),
        "hostname": get_hostname()
    }
    
    # Database size
    db_path = os.path.join(DATA_DIR, "dapx.db")
    if os.path.exists(db_path):
        info["database"]["size"] = os.path.getsize(db_path)
    
    # SSH keys
    ssh_files = ["id_rsa", "id_rsa.pub", "id_ed25519", "id_ed25519.pub", "known_hosts"]
    for ssh_file in ssh_files:
        path = os.path.join(SSH_DIR, ssh_file)
        if os.path.exists(path):
            info["ssh_keys"]["exists"] = True
            info["ssh_keys"]["files"].append(ssh_file)
    
    # Certificates
    cert_paths = [os.path.join(CONFIG_DIR, "ssl"), os.path.join(INSTALL_DIR, "ssl")]
    for cert_dir in cert_paths:
        if os.path.exists(cert_dir):
            for cert_file in os.listdir(cert_dir):
                if cert_file.endswith(('.pem', '.crt', '.key')):
                    info["certificates"]["exists"] = True
                    info["certificates"]["files"].append(cert_file)
    
    return info
