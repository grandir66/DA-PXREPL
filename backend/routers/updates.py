"""
DAPX-backandrepl - Sistema di Aggiornamento
Gestione aggiornamenti da interfaccia web
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import subprocess
import os
import logging
import asyncio
from datetime import datetime
import json
import httpx

from database import get_db, SessionLocal
from routers.auth import require_admin, User

router = APIRouter(prefix="/api/updates", tags=["updates"])
logger = logging.getLogger(__name__)

# Stato aggiornamento globale
update_status = {
    "in_progress": False,
    "last_check": None,
    "last_update": None,
    "current_version": None,
    "available_version": None,
    "update_available": False,
    "log": [],
    "error": None
}

# Configurazione
GITHUB_REPO = "grandir66/DA-PXREPL"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
INSTALL_DIR = "/opt/dapx-unified"
VERSION_FILE = os.path.join(INSTALL_DIR, "version.json")

# Modelli
class UpdateCheckResponse(BaseModel):
    current_version: str
    available_version: Optional[str]
    update_available: bool
    last_check: Optional[str]
    changelog: Optional[str] = None
    release_date: Optional[str] = None
    release_url: Optional[str] = None

class UpdateStatusResponse(BaseModel):
    in_progress: bool
    last_update: Optional[str]
    log: List[str]
    error: Optional[str]
    success: Optional[bool] = None

class UpdateStartResponse(BaseModel):
    success: bool
    message: str


def get_current_version() -> str:
    """Ottieni versione corrente installata da version.json"""
    try:
        # Lista di percorsi da provare
        version_paths = [
            VERSION_FILE,
            os.path.join(INSTALL_DIR, "version.json"),
            "/opt/dapx-unified/version.json",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "version.json"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "version.json"),
        ]
        
        for version_file in version_paths:
            if os.path.exists(version_file):
                try:
                    with open(version_file, 'r') as f:
                        data = json.load(f)
                        version = data.get("version", "unknown")
                        if version and version != "":
                            logger.debug(f"Versione letta da {version_file}: {version}")
                            return version
                except json.JSONDecodeError:
                    # Potrebbe essere un file VERSION vecchio stile
                    try:
                        with open(version_file, 'r') as f:
                            version = f.read().strip().split('\n')[0].strip()
                            if version:
                                return version
                    except:
                        pass
                except Exception as e:
                    logger.warning(f"Errore lettura file versione {version_file}: {e}")
                    continue
        
        # Fallback: git describe
        if os.path.exists(os.path.join(INSTALL_DIR, ".git")):
            result = subprocess.run(
                ["git", "describe", "--tags", "--always", "--dirty"],
                cwd=INSTALL_DIR,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                version = result.stdout.strip().lstrip("v")
                logger.debug(f"Versione da git describe: {version}")
                return version
        
        logger.warning("Impossibile determinare versione, uso 'unknown'")
        return "unknown"
    except Exception as e:
        logger.error(f"Errore lettura versione: {e}")
        return "unknown"


async def get_latest_release() -> Dict[str, Any]:
    """Ottieni ultima release/tag da GitHub"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Prova prima le releases
            try:
                response = await client.get(
                    f"{GITHUB_API}/releases/latest",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                
                # Controlla rate limit
                if response.status_code == 403:
                    logger.warning("GitHub API rate limit raggiunto")
                    return {
                        "version": "rate_limit",
                        "changelog": "GitHub API rate limit raggiunto. Riprova tra qualche minuto.",
                        "date": "",
                        "url": "",
                        "prerelease": False,
                        "error": "rate_limit"
                    }
                
                if response.status_code == 200:
                    data = response.json()
                    version = data.get("tag_name", "")
                    if version:
                        logger.info(f"Trovata release GitHub: {version}")
                        return {
                            "version": version.lstrip("v"),
                            "changelog": data.get("body", ""),
                            "date": data.get("published_at", ""),
                            "url": data.get("html_url", ""),
                            "prerelease": data.get("prerelease", False)
                        }
            except Exception as e:
                logger.warning(f"Errore recupero releases GitHub: {e}")
            
            # Se non ci sono releases, prova con i tags
            try:
                response = await client.get(
                    f"{GITHUB_API}/tags",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                
                # Controlla rate limit
                if response.status_code == 403:
                    logger.warning("GitHub API rate limit raggiunto")
                    return {
                        "version": "rate_limit",
                        "changelog": "GitHub API rate limit raggiunto. Riprova tra qualche minuto.",
                        "date": "",
                        "url": "",
                        "prerelease": False,
                        "error": "rate_limit"
                    }
                
                if response.status_code == 200:
                    tags = response.json()
                    if tags and len(tags) > 0:
                        # Prendi il primo tag (il più recente)
                        latest_tag = tags[0]
                        tag_name = latest_tag.get("name", "")
                        if tag_name:
                            logger.info(f"Trovato tag GitHub: {tag_name}")
                            # Ottieni info sul commit del tag
                            commit_url = latest_tag.get("commit", {}).get("url", "")
                            commit_date = ""
                            commit_message = ""
                            if commit_url:
                                try:
                                    commit_response = await client.get(
                                        commit_url,
                                        headers={"Accept": "application/vnd.github.v3+json"}
                                    )
                                    if commit_response.status_code == 200:
                                        commit_data = commit_response.json()
                                        commit_date = commit_data.get("commit", {}).get("author", {}).get("date", "")
                                        commit_message = commit_data.get("commit", {}).get("message", "")
                                except Exception:
                                    pass
                            
                            return {
                                "version": tag_name.lstrip("v"),
                                "changelog": commit_message or f"Tag {tag_name}",
                                "date": commit_date,
                                "url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}",
                                "prerelease": False
                            }
            except Exception as e:
                logger.warning(f"Errore recupero tags GitHub: {e}")
            
            # Se non ci sono né releases né tags, usa i commit
            try:
                response = await client.get(
                    f"{GITHUB_API}/commits/main",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                
                # Controlla rate limit
                if response.status_code == 403:
                    logger.warning("GitHub API rate limit raggiunto")
                    return {
                        "version": "rate_limit",
                        "changelog": "GitHub API rate limit raggiunto. Riprova tra qualche minuto.",
                        "date": "",
                        "url": "",
                        "prerelease": False,
                        "error": "rate_limit"
                    }
                
                if response.status_code == 200:
                    data = response.json()
                    sha = data.get("sha", "")
                    if sha:
                        logger.info(f"Usato commit come versione: {sha[:7]}")
                        return {
                            "version": sha[:7],
                            "changelog": data.get("commit", {}).get("message", ""),
                            "date": data.get("commit", {}).get("author", {}).get("date", ""),
                            "url": data.get("html_url", ""),
                            "prerelease": False
                        }
            except Exception as e:
                logger.warning(f"Errore recupero commits GitHub: {e}")
            
            # Fallback: restituisci un dizionario vuoto invece di None
            logger.warning("Impossibile recuperare informazioni da GitHub")
            return {
                "version": "",
                "changelog": "",
                "date": "",
                "url": "",
                "prerelease": False
            }
    except Exception as e:
        logger.error(f"Errore connessione GitHub: {e}")
        # Restituisci un dizionario vuoto invece di None per evitare errori
        return {
            "version": "",
            "changelog": "",
            "date": "",
            "url": "",
            "prerelease": False
        }


async def run_update_process():
    """Esegue il processo di aggiornamento"""
    global update_status
    
    update_status["in_progress"] = True
    update_status["log"] = []
    update_status["error"] = None
    
    def log(msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        update_status["log"].append(f"[{timestamp}] {msg}")
        logger.info(f"Update: {msg}")
    
    try:
        log("Avvio aggiornamento...")
        
        # Verifica directory installazione
        if not os.path.exists(INSTALL_DIR):
            raise Exception(f"Directory installazione non trovata: {INSTALL_DIR}")
        
        # Backup database
        log("Creazione backup database...")
        backup_dir = "/var/lib/dapx-unified/backups"
        os.makedirs(backup_dir, exist_ok=True)
        
        db_path = "/var/lib/dapx-unified/dapx.db"
        if os.path.exists(db_path):
            backup_name = f"backup_pre_update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            subprocess.run(["cp", db_path, os.path.join(backup_dir, backup_name)])
            log(f"Backup creato: {backup_name}")
        
        # Aggiorna codice da Git
        log("Download aggiornamenti da GitHub...")
        
        if os.path.exists(os.path.join(INSTALL_DIR, ".git")):
            # Repository Git esistente
            result = subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=INSTALL_DIR,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise Exception(f"Errore git fetch: {result.stderr}")
            
            result = subprocess.run(
                ["git", "reset", "--hard", "origin/main"],
                cwd=INSTALL_DIR,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise Exception(f"Errore git reset: {result.stderr}")
            
            log("Codice aggiornato da Git")
        else:
            raise Exception("La directory non è un repository Git")
        
        # Aggiorna dipendenze Python (usa venv se esiste)
        log("Aggiornamento dipendenze Python...")
        venv_pip = os.path.join(INSTALL_DIR, "venv", "bin", "pip")
        requirements = os.path.join(INSTALL_DIR, "backend", "requirements.txt")
        
        if os.path.exists(venv_pip):
            result = subprocess.run(
                [venv_pip, "install", "-r", requirements, "--quiet", "--upgrade"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                log(f"Warning dipendenze: {result.stderr[:200] if result.stderr else 'errore pip'}")
            else:
                log("Dipendenze Python aggiornate")
        else:
            log("Warning: venv non trovato, skip dipendenze Python")
        
        # Ricompila Frontend
        log("Ricompilazione frontend...")
        frontend_dir = os.path.join(INSTALL_DIR, "frontend")
        
        if os.path.exists(os.path.join(frontend_dir, "package.json")):
            # npm install
            result = subprocess.run(
                ["npm", "install", "--silent"],
                cwd=frontend_dir,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                log(f"Warning npm install: {result.stderr[:100] if result.stderr else ''}")
            
            # npm run build
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=frontend_dir,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                log("Frontend ricompilato con successo")
            else:
                log(f"Warning build frontend: {result.stderr[:200] if result.stderr else 'errore build'}")
        else:
            log("Warning: frontend/package.json non trovato")
        
        # Ricarica e riavvia servizio
        log("Ricarica configurazione systemd...")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
        
        log("Riavvio servizio dapx-unified...")
        result = subprocess.run(
            ["systemctl", "restart", "dapx-unified"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            log("Servizio dapx-unified riavviato")
        else:
            log(f"Warning riavvio servizio: {result.stderr}")
        
        # Attendi che il servizio sia pronto
        await asyncio.sleep(3)
        
        # Verifica servizio
        log("Verifica servizio...")
        result = subprocess.run(
            ["systemctl", "is-active", "dapx-unified"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            log("Servizio dapx-unified attivo")
        else:
            log("Warning: servizio dapx-unified non risulta attivo")
        
        # Leggi nuova versione
        log("Lettura versione aggiornata...")
        import time
        time.sleep(0.5)
        
        new_version = get_current_version()
        old_version = update_status.get("current_version", "unknown")
        
        update_status["current_version"] = new_version
        update_status["last_update"] = datetime.now().isoformat()
        update_status["update_available"] = False
        
        log(f"Versione aggiornata: {old_version} → {new_version}")
        log("✓ Aggiornamento completato con successo!")
        
    except Exception as e:
        logger.error(f"Errore aggiornamento: {e}")
        update_status["error"] = str(e)
        update_status["log"].append(f"[ERRORE] {str(e)}")
    
    finally:
        update_status["in_progress"] = False


@router.get("/check", response_model=UpdateCheckResponse)
async def check_for_updates(user: User = Depends(require_admin)):
    """Verifica se ci sono aggiornamenti disponibili"""
    global update_status
    
    current = get_current_version()
    update_status["current_version"] = current
    
    latest = await get_latest_release()
    
    if latest:
        available = latest.get("version", "")
        update_status["available_version"] = available
        update_status["last_check"] = datetime.now().isoformat()
        
        # Confronta versioni (semplificato)
        update_available = False
        if current != available and available:
            # Se la versione corrente è un hash corto, confronta
            if len(current) == 7 and len(available) >= 7:
                update_available = current != available[:7]
            else:
                update_available = current != available
        
        update_status["update_available"] = update_available
        
        return UpdateCheckResponse(
            current_version=current,
            available_version=available,
            update_available=update_available,
            last_check=update_status["last_check"],
            changelog=latest.get("changelog"),
            release_date=latest.get("date"),
            release_url=latest.get("url")
        )
    
    return UpdateCheckResponse(
        current_version=current,
        available_version=None,
        update_available=False,
        last_check=datetime.now().isoformat()
    )


@router.get("/status", response_model=UpdateStatusResponse)
async def get_update_status(user: User = Depends(require_admin)):
    """Ottieni stato aggiornamento in corso"""
    return UpdateStatusResponse(
        in_progress=update_status["in_progress"],
        last_update=update_status["last_update"],
        log=update_status["log"],
        error=update_status["error"],
        success=update_status["error"] is None if update_status["log"] else None
    )


@router.post("/start", response_model=UpdateStartResponse)
async def start_update(
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin)
):
    """Avvia aggiornamento"""
    global update_status
    
    if update_status["in_progress"]:
        raise HTTPException(status_code=409, detail="Aggiornamento già in corso")
    
    # Avvia aggiornamento in background
    background_tasks.add_task(run_update_process)
    
    return UpdateStartResponse(
        success=True,
        message="Aggiornamento avviato. Controlla lo stato per i progressi."
    )


@router.get("/version")
async def get_version():
    """Ottieni versione corrente (pubblico)"""
    version = get_current_version()
    version_file_exists = os.path.exists(VERSION_FILE)
    return {
        "version": version,
        "install_dir": INSTALL_DIR,
        "version_file": VERSION_FILE,
        "version_file_exists": version_file_exists,
        "version_file_content": None if not version_file_exists else open(VERSION_FILE, 'r').read().strip()
    }


@router.post("/refresh-version")
async def refresh_version(user: User = Depends(require_admin)):
    """Forza refresh della versione (utile dopo aggiornamento)"""
    try:
        # Forza rilettura del file VERSION
        version = get_current_version()
        update_status["current_version"] = version
        
        # Verifica anche se il file esiste
        version_file_exists = os.path.exists(VERSION_FILE)
        version_file_content = None
        if version_file_exists:
            with open(VERSION_FILE, 'r') as f:
                version_file_content = f.read().strip()
        
        return {
            "success": True,
            "version": version,
            "version_file": VERSION_FILE,
            "version_file_exists": version_file_exists,
            "version_file_content": version_file_content,
            "message": f"Versione aggiornata: {version}"
        }
    except Exception as e:
        logger.error(f"Errore refresh versione: {e}")
        raise HTTPException(status_code=500, detail=f"Errore refresh versione: {str(e)}")


@router.get("/debug-github")
async def debug_github():
    """Debug: testa connessione a GitHub e recupero versione"""
    results = {
        "current_version": get_current_version(),
        "github_api": GITHUB_API,
        "tests": {}
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Test releases
            try:
                response = await client.get(
                    f"{GITHUB_API}/releases/latest",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                results["tests"]["releases"] = {
                    "status_code": response.status_code,
                    "success": response.status_code == 200,
                    "data": response.json() if response.status_code == 200 else response.text[:200]
                }
            except Exception as e:
                results["tests"]["releases"] = {"error": str(e)}
            
            # Test tags
            try:
                response = await client.get(
                    f"{GITHUB_API}/tags",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                if response.status_code == 200:
                    tags = response.json()
                    results["tests"]["tags"] = {
                        "status_code": response.status_code,
                        "success": True,
                        "count": len(tags),
                        "first_tag": tags[0] if tags else None
                    }
                else:
                    results["tests"]["tags"] = {
                        "status_code": response.status_code,
                        "success": False,
                        "data": response.text[:200]
                    }
            except Exception as e:
                results["tests"]["tags"] = {"error": str(e)}
            
            # Test commits
            try:
                response = await client.get(
                    f"{GITHUB_API}/commits/main",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                if response.status_code == 200:
                    data = response.json()
                    results["tests"]["commits"] = {
                        "status_code": response.status_code,
                        "success": True,
                        "sha": data.get("sha", "")[:7],
                        "message": data.get("commit", {}).get("message", "")[:100]
                    }
                else:
                    results["tests"]["commits"] = {
                        "status_code": response.status_code,
                        "success": False
                    }
            except Exception as e:
                results["tests"]["commits"] = {"error": str(e)}
                
    except Exception as e:
        results["httpx_error"] = str(e)
    
    # Test get_latest_release
    try:
        latest = await get_latest_release()
        results["get_latest_release_result"] = latest
    except Exception as e:
        results["get_latest_release_error"] = str(e)
    
    return results

