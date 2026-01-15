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
BRANCH="${1:-main}"

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

# Scarica version.json remoto
REMOTE_VERSION_URL="https://raw.githubusercontent.com/grandir66/DA-PXREPL/$BRANCH/version.json"
REMOTE_VERSION_JSON=$(curl -s "$REMOTE_VERSION_URL" 2>/dev/null || echo "")

if [ -n "$REMOTE_VERSION_JSON" ]; then
    REMOTE_VERSION=$(echo "$REMOTE_VERSION_JSON" | grep '"version"' | cut -d'"' -f4)
    REMOTE_DATE=$(echo "$REMOTE_VERSION_JSON" | grep '"build_date"' | cut -d'"' -f4)
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
compare_versions "$CURRENT_VERSION" "$REMOTE_VERSION"
COMP_RESULT=$?

if [ $COMP_RESULT -eq 0 ]; then
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ Sei già all'ultima versione! ($CURRENT_VERSION)     ${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo ""
    read -p "Vuoi forzare la reinstallazione comunque? [y/N]: " force
    if [[ ! "$force" =~ ^[Yy]$ ]]; then
        echo "Nessun aggiornamento necessario."
        exit 0
    fi
elif [ $COMP_RESULT -eq 1 ]; then
    log_warn "La versione locale ($CURRENT_VERSION) è più recente di quella remota ($REMOTE_VERSION)"
    read -p "Vuoi fare downgrade? [y/N]: " downgrade
    if [[ ! "$downgrade" =~ ^[Yy]$ ]]; then
        exit 0
    fi
else
    echo -e "${YELLOW}════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  ⬆ Aggiornamento disponibile!                          ${NC}"
    echo -e "${YELLOW}    $CURRENT_VERSION → $REMOTE_VERSION                  ${NC}"
    echo -e "${YELLOW}════════════════════════════════════════════════════════${NC}"
    echo ""
    read -p "Procedere con l'aggiornamento? [Y/n]: " proceed
    if [[ "$proceed" =~ ^[Nn]$ ]]; then
        exit 0
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

if [ -d ".git" ]; then
    log_info "Repository Git rilevato, pull in corso..."
    git fetch origin
    git checkout $BRANCH
    git reset --hard origin/$BRANCH
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

# Frontend rebuild
echo -e "\n${BOLD}Rebuild Frontend${NC}\n"

if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    cd frontend
    log_info "Installazione dipendenze npm..."
    npm install --silent
    log_info "Compilazione frontend..."
    npm run build
    cd ..
    log_success "Frontend ricompilato"
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
    
    # Mostra URL
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
    echo -e "  Accesso: ${CYAN}http://${LOCAL_IP}:8420${NC}"
    echo ""
else
    log_error "Errore avvio servizio"
    echo "Controlla i log: journalctl -u dapx-unified -n 50"
    
    # Offri rollback
    echo ""
    read -p "Vuoi ripristinare il backup? [y/N]: " rollback
    if [[ "$rollback" =~ ^[Yy]$ ]]; then
        if [ -f "$BACKUP_FILE" ]; then
            cp "$BACKUP_FILE" "$DATA_DIR/dapx.db"
            log_info "Database ripristinato"
        fi
        systemctl start dapx-unified || true
    fi
    exit 1
fi
