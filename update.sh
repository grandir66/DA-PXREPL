#!/bin/bash
#
# DAPX-Unified - Update Script
# Aggiornamento da repository Git con verifica versione
#

set -e

# Configurazioni
INSTALL_DIR="/opt/dapx-unified"
DATA_DIR="/var/lib/dapx-unified"
REPO_URL="https://github.com/grandir66/DA-PXREPL.git"
BRANCH="main"
ASSUME_YES=0
UPGRADE_NODE=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes|--non-interactive)
            ASSUME_YES=1
            ;;
        --upgrade-node)
            UPGRADE_NODE=1
            ;;
        -h|--help)
            echo "Uso: $0 [-y|--yes] [--upgrade-node] [branch]"
            echo "  -y, --yes        Non interattivo (assume Y a tutti i prompt)"
            echo "  --upgrade-node   Installa/aggiorna Node a 20 LTS prima del rebuild"
            echo "  branch           Branch git da cui aggiornare (default: main)"
            exit 0
            ;;
        -*)
            echo "Opzione sconosciuta: $arg" >&2
            exit 2
            ;;
        *)
            BRANCH="$arg"
            ;;
    esac
done

# Se stdin non e' un terminale (es. pct exec, pipe), forza non-interattivo
if [ ! -t 0 ]; then
    ASSUME_YES=1
fi

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║                                                           ║"
    echo "║              DAPX-Unified Update Manager                  ║"
    echo "║                                                           ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }

print_banner

# Check root
if [ "$EUID" -ne 0 ]; then 
    log_error "Questo script deve essere eseguito come root"
    exit 1
fi

# Verifica installazione esistente
if [ ! -d "$INSTALL_DIR" ]; then
    log_error "DAPX-Unified non sembra essere installato in $INSTALL_DIR"
    echo -e "Esegui prima ${YELLOW}install.sh${NC} per l'installazione"
    exit 1
fi

cd "$INSTALL_DIR"

# ============== VERIFICA VERSIONI ==============

echo -e "\n${BOLD}Verifica Versioni${NC}\n"

# Versione attuale (locale)
if [ -f "version.json" ]; then
    CURRENT_VERSION=$(grep '"version"' version.json | cut -d'"' -f4)
    CURRENT_DATE=$(grep '"build_date"' version.json | cut -d'"' -f4)
    log_success "Versione installata: ${BOLD}$CURRENT_VERSION${NC} ($CURRENT_DATE)"
else
    CURRENT_VERSION="0.0.0"
    log_warn "File version.json non trovato, versione sconosciuta"
fi

# Fetch versione remota
log_info "Controllo versione su GitHub..."

# Sorgente preferita: GitHub Releases API (sempre fresca, no CDN cache).
# Fallback: version.json su raw.githubusercontent.com (con cache-buster) — il
# CDN ha TTL ~5min e ignora spesso Cache-Control, quindi puo' restituire
# valori vecchi. Per questo l'API releases e' la prima scelta.
REMOTE_VERSION=""
REMOTE_DATE=""

RELEASE_API_URL="https://api.github.com/repos/grandir66/DA-PXREPL/releases/latest"
RELEASE_JSON=$(curl -s -H 'Accept: application/vnd.github+json' "$RELEASE_API_URL" 2>/dev/null || echo "")
if [ -n "$RELEASE_JSON" ]; then
    # Estrae tag_name (es. "v3.12.1") e rimuove la "v" iniziale
    REMOTE_VERSION=$(echo "$RELEASE_JSON" | grep -m1 '"tag_name"' | cut -d'"' -f4 | sed 's/^v//')
    REMOTE_DATE=$(echo "$RELEASE_JSON" | grep -m1 '"published_at"' | cut -d'"' -f4 | cut -dT -f1)
fi

# Fallback su raw version.json se l'API non ha risposto o non ha trovato release
if [ -z "$REMOTE_VERSION" ]; then
    REMOTE_VERSION_URL="https://raw.githubusercontent.com/grandir66/DA-PXREPL/$BRANCH/version.json?t=$(date +%s)"
    REMOTE_VERSION_JSON=$(curl -s -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' "$REMOTE_VERSION_URL" 2>/dev/null || echo "")
    if [ -n "$REMOTE_VERSION_JSON" ]; then
        REMOTE_VERSION=$(echo "$REMOTE_VERSION_JSON" | grep '"version"' | cut -d'"' -f4)
        REMOTE_DATE=$(echo "$REMOTE_VERSION_JSON" | grep '"build_date"' | cut -d'"' -f4)
    fi
fi

if [ -n "$REMOTE_VERSION" ]; then
    log_success "Versione disponibile: ${BOLD}$REMOTE_VERSION${NC} ($REMOTE_DATE)"
else
    log_error "Impossibile recuperare versione remota"
    log_warn "Verifica la connessione internet"
    exit 1
fi

# Confronta versioni
compare_versions() {
    # Ritorna 0 se $1 == $2, 1 se $1 > $2, 2 se $1 < $2
    if [ "$1" == "$2" ]; then
        return 0
    fi
    
    local IFS=.
    local i ver1=($1) ver2=($2)
    
    for ((i=0; i<${#ver1[@]}; i++)); do
        if [ -z "${ver2[i]}" ]; then
            ver2[i]=0
        fi
        if [ "${ver1[i]}" -gt "${ver2[i]}" ]; then
            return 1
        fi
        if [ "${ver1[i]}" -lt "${ver2[i]}" ]; then
            return 2
        fi
    done
    return 0
}

echo ""
# NB: compare_versions ritorna 1 o 2 per indicare maggiore/minore. Con `set -e`
# attivo, una funzione che ritorna != 0 fa abortire lo script PRIMA del prompt
# (bug storico: lo script si chiudeva silenziosamente dopo "Versione disponibile").
# Catturiamo l'exit code in modo che set -e non scatti.
COMP_RESULT=0
compare_versions "$CURRENT_VERSION" "$REMOTE_VERSION" || COMP_RESULT=$?

# Anche a parità di version.json, origin/main può avere commit più recenti.
GIT_UPDATE_NEEDED=0
GIT_FETCH_OK=1
if [ -d ".git" ]; then
    if ! git fetch origin "$BRANCH" 2>/dev/null; then
        GIT_FETCH_OK=0
        log_warn "git fetch fallito: confronto SHA remoto non affidabile"
    fi
    LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
    REMOTE_SHA=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
    if [ -n "$LOCAL_SHA" ] && [ -n "$REMOTE_SHA" ] && [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
        GIT_UPDATE_NEEDED=1
        log_info "Commit locale (${LOCAL_SHA:0:7}) diverso da origin/$BRANCH (${REMOTE_SHA:0:7})"
    elif [ "$GIT_FETCH_OK" -eq 0 ]; then
        GIT_UPDATE_NEEDED=1
        log_warn "Procedo con aggiornamento conservativo (fetch non riuscito)"
    fi
fi

if [ $COMP_RESULT -eq 0 ] && [ $GIT_UPDATE_NEEDED -eq 0 ]; then
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ Sei già all'ultima versione! ($CURRENT_VERSION)     ${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    if [ "$ASSUME_YES" -eq 1 ]; then
        echo "Nessun aggiornamento necessario (modalita' non interattiva)."
        exit 0
    fi
    read -p "Vuoi forzare la reinstallazione comunque? [y/N]: " force
    if [[ ! "$force" =~ ^[Yy]$ ]]; then
        echo "Nessun aggiornamento necessario."
        exit 0
    fi
elif [ $COMP_RESULT -eq 0 ] && [ $GIT_UPDATE_NEEDED -eq 1 ]; then
    echo -e "${YELLOW}════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  ⬆ Stessa versione ($CURRENT_VERSION) ma nuovi commit su Git  ${NC}"
    echo -e "${YELLOW}════════════════════════════════════════════════════════${NC}"
    echo ""
    if [ "$ASSUME_YES" -eq 1 ]; then
        log_info "Procedo con l'aggiornamento codice (modalita' non interattiva)"
    else
        read -p "Procedere con l'aggiornamento del codice? [Y/n]: " proceed
        if [[ "$proceed" =~ ^[Nn]$ ]]; then
            exit 0
        fi
    fi
elif [ $COMP_RESULT -eq 1 ]; then
    log_warn "La versione locale ($CURRENT_VERSION) è più recente di quella remota ($REMOTE_VERSION)"
    if [ $GIT_UPDATE_NEEDED -eq 1 ]; then
        echo -e "${YELLOW}  Nuovi commit su Git disponibili nonostante version.json locale più recente${NC}"
        if [ "$ASSUME_YES" -eq 1 ]; then
            log_info "Procedo con aggiornamento codice (modalita' non interattiva)"
        else
            read -p "Procedere con l'aggiornamento del codice? [Y/n]: " proceed
            if [[ "$proceed" =~ ^[Nn]$ ]]; then
                exit 0
            fi
        fi
    else
        if [ "$ASSUME_YES" -eq 1 ]; then
            log_info "Salto downgrade (modalita' non interattiva)"
            exit 0
        fi
        read -p "Vuoi fare downgrade? [y/N]: " downgrade
        if [[ ! "$downgrade" =~ ^[Yy]$ ]]; then
            exit 0
        fi
    fi
else
    echo -e "${YELLOW}════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  ⬆ Aggiornamento disponibile!                          ${NC}"
    echo -e "${YELLOW}    $CURRENT_VERSION → $REMOTE_VERSION                  ${NC}"
    echo -e "${YELLOW}════════════════════════════════════════════════════════${NC}"
    echo ""
    if [ "$ASSUME_YES" -eq 1 ]; then
        log_info "Procedo con l'aggiornamento (modalita' non interattiva)"
    else
        read -p "Procedere con l'aggiornamento? [Y/n]: " proceed
        if [[ "$proceed" =~ ^[Nn]$ ]]; then
            exit 0
        fi
    fi
fi

# ============== BACKUP ==============

echo -e "\n${BOLD}Backup${NC}\n"

BACKUP_DIR="$DATA_DIR/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d%H%M%S)

# Backup database
if [ -f "$DATA_DIR/dapx.db" ]; then
    BACKUP_FILE="$BACKUP_DIR/dapx.db.pre-update-$TIMESTAMP"
    cp "$DATA_DIR/dapx.db" "$BACKUP_FILE"
    log_success "Database backuppato: $BACKUP_FILE"
fi

# Backup config
if [ -f "/etc/dapx-unified/dapx-unified.env" ]; then
    cp "/etc/dapx-unified/dapx-unified.env" "$BACKUP_DIR/dapx-unified.env.pre-update-$TIMESTAMP"
    log_success "Configurazione backuppata"
fi

# ============== STOP SERVICE ==============

echo -e "\n${BOLD}Arresto Servizio${NC}\n"

if systemctl is-active --quiet dapx-unified 2>/dev/null; then
    systemctl stop dapx-unified
    log_success "Servizio arrestato"
else
    log_info "Servizio non in esecuzione"
fi

# ============== UPDATE ==============

echo -e "\n${BOLD}Download Aggiornamenti${NC}\n"

cd "$INSTALL_DIR"

# ============== MIGRAZIONE LAYOUT LEGACY (v3.17.4+) ==============
# Le installazioni create prima della v3.17.4 avevano i file backend
# spalmati direttamente in $INSTALL_DIR (main.py, database.py,
# routers/, services/ alla root). Dalla v3.17.4 il layout
# deterministico è $INSTALL_DIR/backend/. Se rileviamo il layout
# legacy lo spostiamo in un backup PRIMA del git pull, perché:
#   1) git reset --hard non tocca file non-tracked (i legacy non lo
#      sono, sono stati copiati da install.sh) → resterebbero a
#      shadow del backend/ del repo;
#   2) Python con cwd=$INSTALL_DIR risolverebbe `import main`,
#      `import routers.x` dai file legacy invece che da backend/,
#      facendo girare codice vecchio anche dopo update riuscito.
if [ -f "$INSTALL_DIR/main.py" ] && [ -d "$INSTALL_DIR/routers" ] && [ -d "$INSTALL_DIR/backend" ]; then
    LEGACY_BAK="$INSTALL_DIR/_legacy_backup_$(date +%Y%m%d%H%M%S)"
    log_warn "Layout legacy rilevato (main.py + routers/ accanto a backend/)"
    log_info "Sposto i file legacy in $LEGACY_BAK"
    mkdir -p "$LEGACY_BAK"
    for legacy_item in main.py database.py update_db_schema.py routers services; do
        if [ -e "$INSTALL_DIR/$legacy_item" ]; then
            mv "$INSTALL_DIR/$legacy_item" "$LEGACY_BAK/" 2>/dev/null || true
        fi
    done
    log_success "Layout legacy migrato (backup in $LEGACY_BAK)"
fi

if [ -d ".git" ]; then
    log_info "Repository Git rilevato, pull in corso..."
    git fetch origin
    git checkout $BRANCH
    git reset --hard origin/$BRANCH
    # Pulisci eventuali __pycache__ residui dopo il reset.
    find "$INSTALL_DIR/backend" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    log_success "Codice aggiornato da Git"
else
    log_warn "Non è un repository Git, re-clone in corso..."
    cd /opt
    rm -rf dapx-unified-backup 2>/dev/null || true
    mv dapx-unified dapx-unified-backup
    git clone --branch $BRANCH $REPO_URL dapx-unified
    
    # Ripristina venv se esistente
    if [ -d "dapx-unified-backup/venv" ]; then
        mv dapx-unified-backup/venv dapx-unified/
    fi
    
    cd dapx-unified
    log_success "Repository clonato"
fi

# ============== UPDATE DEPENDENCIES ==============

echo -e "\n${BOLD}Aggiornamento Dipendenze${NC}\n"

# Python
if [ -d "venv" ]; then
    log_info "Aggiornamento dipendenze Python..."
    source venv/bin/activate
    pip install -r backend/requirements.txt --quiet --upgrade
    deactivate
    log_success "Dipendenze Python aggiornate"
else
    log_warn "Virtual environment non trovato, creazione..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r backend/requirements.txt --quiet
    deactivate
    log_success "Virtual environment creato e configurato"
fi

# Frontend rebuild — best effort.
# Se npm manca o la build fallisce (es. Node troppo vecchio per Vite),
# usiamo il frontend/dist precompilato gia' presente nel repo, che e'
# stato aggiornato dal git pull.
echo -e "\n${BOLD}Rebuild Frontend${NC}\n"

frontend_use_prebuilt() {
    if [ -d "frontend/dist" ] && [ "$(ls -A frontend/dist 2>/dev/null)" ]; then
        log_success "Uso frontend/dist precompilato dal repo (nessuna build necessaria)"
        return 0
    fi
    log_warn "frontend/dist non disponibile, l'interfaccia potrebbe non aggiornarsi"
    return 1
}

install_node_20_lts() {
    # Installa Node 20 LTS via NodeSource. Idempotente.
    log_info "Installazione Node 20 LTS via NodeSource..."
    if ! command -v curl >/dev/null 2>&1; then
        apt-get update -qq >/dev/null 2>&1 || true
        apt-get install -y -qq curl >/dev/null 2>&1 || true
    fi
    if curl -fsSL https://deb.nodesource.com/setup_20.x 2>/dev/null | bash - >/dev/null 2>&1; then
        if apt-get install -y -qq nodejs >/dev/null 2>&1; then
            log_success "Node $(node --version 2>/dev/null) installato"
            return 0
        fi
    fi
    log_warn "Installazione Node 20 fallita (verificare connettivita' o repo apt)"
    return 1
}

# Estrai major.minor di Node, ritorna 0 se >= MIN, 1 altrimenti.
node_meets_min() {
    local min_major="$1"
    local min_minor="$2"
    local v
    v=$(node --version 2>/dev/null | sed 's/^v//') || return 1
    local major=${v%%.*}
    local rest=${v#*.}
    local minor=${rest%%.*}
    if [ -z "$major" ] || [ -z "$minor" ]; then return 1; fi
    if [ "$major" -gt "$min_major" ]; then return 0; fi
    if [ "$major" -lt "$min_major" ]; then return 1; fi
    if [ "$minor" -ge "$min_minor" ]; then return 0; fi
    return 1
}

do_npm_build() {
    pushd frontend >/dev/null
    log_info "Installazione dipendenze npm..."
    if ! npm install --silent 2>/dev/null; then
        log_warn "npm install ha riportato errori, proseguo comunque"
    fi
    log_info "Compilazione frontend..."
    if npm run build >/tmp/dapx-vite-build.log 2>&1; then
        log_success "Frontend ricompilato"
        popd >/dev/null
        return 0
    else
        log_warn "Build npm fallita (log in /tmp/dapx-vite-build.log)"
        popd >/dev/null
        return 1
    fi
}

if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
        log_warn "node/npm non installati"
        if [ "$UPGRADE_NODE" -eq 1 ] || [ "$ASSUME_YES" -eq 1 ]; then
            install_node_20_lts || true
        fi
        if command -v npm >/dev/null 2>&1 && command -v node >/dev/null 2>&1 && node_meets_min 20 19; then
            do_npm_build || frontend_use_prebuilt
        else
            frontend_use_prebuilt
        fi
    elif ! node_meets_min 20 19; then
        # Vite >= 7 richiede Node 20.19+. Default Debian 12 = Node 18.
        # Proponiamo l'aggiornamento (o lo facciamo se --upgrade-node /
        # --yes), altrimenti silenziosamente usiamo il dist precompilato.
        log_warn "Node $(node --version 2>/dev/null) troppo vecchio per Vite >=7 (richiede 20.19+)"
        do_upgrade=0
        if [ "$UPGRADE_NODE" -eq 1 ]; then
            do_upgrade=1
        elif [ "$ASSUME_YES" -eq 0 ]; then
            read -p "Vuoi installare Node 20 LTS adesso? [y/N]: " yn
            case "$yn" in
                [yY]|[yY][eE][sS]) do_upgrade=1 ;;
            esac
        fi
        if [ "$do_upgrade" -eq 1 ] && install_node_20_lts && node_meets_min 20 19; then
            do_npm_build || frontend_use_prebuilt
        else
            log_info "Salto la build npm e uso il frontend precompilato dal repo"
            frontend_use_prebuilt
        fi
    else
        do_npm_build || frontend_use_prebuilt
    fi
else
    log_warn "frontend/package.json non trovato, salto rebuild"
fi

# ============== FIX UNIT + SCHEMA MIGRATION (v3.17.4+) ==============

# Fix WorkingDirectory del systemd unit se ancora puntato a
# $INSTALL_DIR (layout legacy). Dalla v3.17.4 deve puntare a
# $INSTALL_DIR/backend.
UNIT_FILE="/etc/systemd/system/dapx-unified.service"
if [ -f "$UNIT_FILE" ]; then
    if grep -q "^WorkingDirectory=$INSTALL_DIR$" "$UNIT_FILE"; then
        log_warn "Systemd unit usa WorkingDirectory legacy ($INSTALL_DIR)"
        log_info "Aggiorno a $INSTALL_DIR/backend"
        sed -i "s|^WorkingDirectory=$INSTALL_DIR$|WorkingDirectory=$INSTALL_DIR/backend|" "$UNIT_FILE"
        log_success "Systemd unit aggiornato"
    fi
fi

# Esegui esplicitamente la migrazione idempotente dello schema DB.
# main.py la fa già nel lifespan ma è meglio farla qui in modo
# verificabile, per evitare casi in cui il backend parta con schema
# disallineato e gli endpoint falliscano silenziosamente.
if [ -f "$INSTALL_DIR/backend/update_db_schema.py" ] && [ -d "$INSTALL_DIR/venv" ]; then
    log_info "Allineamento schema database..."
    if (cd "$INSTALL_DIR/backend" && "$INSTALL_DIR/venv/bin/python3" update_db_schema.py); then
        log_success "Schema database allineato"
    else
        log_warn "Migrazione schema fallita (non bloccante, main.py riproverà al lifespan)"
    fi
fi

# Ripara ExecStart systemd (venv + SSL) — l'UI SSL legacy usava /usr/bin/python3
# e dopo update/restart il servizio non partiva.
if [ -f "$INSTALL_DIR/backend/scripts/repair_systemd_unit.py" ] && [ -d "$INSTALL_DIR/venv" ]; then
    log_info "Allineamento unit systemd (venv, HTTPS)..."
    if (cd "$INSTALL_DIR/backend" && "$INSTALL_DIR/venv/bin/python3" scripts/repair_systemd_unit.py); then
        log_success "Unit systemd allineato"
    else
        log_warn "Riparazione unit systemd non riuscita (proseguo con unit esistente)"
    fi
fi

# ============== RESTART ==============

echo -e "\n${BOLD}Avvio Servizio${NC}\n"

systemctl daemon-reload
systemctl start dapx-unified

sleep 3

# Verifica
if systemctl is-active --quiet dapx-unified 2>/dev/null; then
    # Leggi nuova versione
    NEW_VERSION=$(grep '"version"' version.json 2>/dev/null | cut -d'"' -f4 || echo "N/A")
    
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}         ✓ AGGIORNAMENTO COMPLETATO!                    ${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  Versione: ${YELLOW}$CURRENT_VERSION${NC} → ${GREEN}$NEW_VERSION${NC}"
    echo ""
    
    # Mostra URL (HTTP o HTTPS se certificati presenti)
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
    ACCESS_SCHEME="http"
    ACCESS_PORT="8420"
    if [ -f "/var/lib/dapx-unified/server_config.json" ]; then
        SCHEME_PORT=$("$INSTALL_DIR/venv/bin/python3" -c "
import json
from pathlib import Path
cfg=json.loads(Path('/var/lib/dapx-unified/server_config.json').read_text())
port=int(cfg.get('port') or 8420)
ssl=bool(cfg.get('ssl_enabled'))
certs=Path('/var/lib/dapx-unified/certs')
if ssl and (certs/'server.crt').exists() and (certs/'server.key').exists():
    print(f'https {port}')
else:
    print(f'http {port}')
" 2>/dev/null || echo "http 8420")
        ACCESS_SCHEME=$(echo "$SCHEME_PORT" | awk '{print $1}')
        ACCESS_PORT=$(echo "$SCHEME_PORT" | awk '{print $2}')
    else
        ACCESS_PORT=8420
    fi
    echo -e "  Accesso: ${CYAN}${ACCESS_SCHEME}://${LOCAL_IP}:${ACCESS_PORT}${NC}"
    echo ""
else
    log_error "Errore avvio servizio"
    echo "Controlla i log: journalctl -u dapx-unified -n 50"
    
    # Offri rollback
    echo ""
    if [ "$ASSUME_YES" -eq 1 ]; then
        rollback="N"
    else
        read -p "Vuoi ripristinare il backup? [y/N]: " rollback
    fi
    if [[ "$rollback" =~ ^[Yy]$ ]]; then
        if [ -f "$BACKUP_FILE" ]; then
            cp "$BACKUP_FILE" "$DATA_DIR/dapx.db"
            log_info "Database ripristinato"
        fi
        systemctl start dapx-unified || true
    fi
    exit 1
fi
