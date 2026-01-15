#!/bin/bash
#
# DA-PXREPL - Update Script
# Aggiornamento da repository Git con verifica versione
#

set -e

# Configurazioni
INSTALL_DIR="/opt/dapx-unified"
REPO_URL="${REPO_URL:-https://github.com/USER/DA-PXREPL.git}"
BRANCH="${1:-main}"

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}        DA-PXREPL - Sistema di Aggiornamento           ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Errore: Eseguire come root (sudo)${NC}"
    exit 1
fi

# Verifica installazione esistente
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}Errore: DA-PXREPL non sembra essere installato in $INSTALL_DIR${NC}"
    echo -e "Esegui prima ${YELLOW}install.sh${NC} per l'installazione"
    exit 1
fi

cd "$INSTALL_DIR"

# Versione attuale
if [ -f "dapx-unified/version.json" ]; then
    CURRENT_VERSION=$(cat dapx-unified/version.json | grep '"version"' | cut -d'"' -f4)
    echo -e "${GREEN}✓ Versione attuale: ${NC}$CURRENT_VERSION"
else
    CURRENT_VERSION="sconosciuta"
    echo -e "${YELLOW}⚠ Versione attuale non rilevata${NC}"
fi

# Fetch updates
echo -e "${BLUE}→ Verifica aggiornamenti...${NC}"

if [ -d ".git" ]; then
    git fetch origin --quiet
    
    # Confronta versioni
    git show origin/$BRANCH:dapx-unified/version.json > /tmp/remote_version.json 2>/dev/null || true
    
    if [ -f /tmp/remote_version.json ]; then
        REMOTE_VERSION=$(cat /tmp/remote_version.json | grep '"version"' | cut -d'"' -f4)
        echo -e "${GREEN}✓ Versione remota:  ${NC}$REMOTE_VERSION"
        
        if [ "$CURRENT_VERSION" == "$REMOTE_VERSION" ]; then
            echo -e "\n${GREEN}✓ Sei già all'ultima versione!${NC}"
            read -p "Vuoi forzare il reinstall comunque? [y/N]: " force
            if [[ ! "$force" =~ ^[Yy]$ ]]; then
                exit 0
            fi
        fi
    fi
else
    echo -e "${YELLOW}⚠ Non è un repository Git, aggiornamento manuale...${NC}"
fi

# Backup
echo -e "${BLUE}→ Backup database...${NC}"
BACKUP_FILE="/var/lib/da-pxrepl/dapx.db.backup-$(date +%Y%m%d%H%M%S)"
if [ -f "/var/lib/da-pxrepl/dapx.db" ]; then
    cp "/var/lib/da-pxrepl/dapx.db" "$BACKUP_FILE"
    echo -e "${GREEN}✓ Backup: $BACKUP_FILE${NC}"
fi

# Stop service
echo -e "${BLUE}→ Stop servizio...${NC}"
systemctl stop da-pxrepl 2>/dev/null || systemctl stop dapx-unified 2>/dev/null || true

# Pull updates
echo -e "${BLUE}→ Download aggiornamenti...${NC}"
if [ -d ".git" ]; then
    git checkout $BRANCH
    git pull origin $BRANCH
else
    # Re-clone se non è un repo git
    cd /opt
    rm -rf dapx-unified-old 2>/dev/null || true
    mv dapx-unified dapx-unified-old 2>/dev/null || true
    git clone --branch $BRANCH $REPO_URL dapx-unified
    cd dapx-unified
fi

# Update backend dependencies
echo -e "${BLUE}→ Aggiornamento dipendenze Python...${NC}"
cd "$INSTALL_DIR/dapx-unified/backend"
if [ -d "venv" ]; then
    source venv/bin/activate
    pip install -r requirements.txt -q --upgrade
    deactivate
fi

# Rebuild frontend
echo -e "${BLUE}→ Rebuild frontend...${NC}"
cd "$INSTALL_DIR/dapx-unified/frontend"
npm install --silent
npm run build

# Restart
echo -e "${BLUE}→ Avvio servizio...${NC}"
systemctl daemon-reload
systemctl start da-pxrepl 2>/dev/null || systemctl start dapx-unified 2>/dev/null

sleep 3

# Verifica
if systemctl is-active --quiet da-pxrepl 2>/dev/null || systemctl is-active --quiet dapx-unified 2>/dev/null; then
    NEW_VERSION=$(cat "$INSTALL_DIR/dapx-unified/version.json" 2>/dev/null | grep '"version"' | cut -d'"' -f4 || echo "N/A")
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}         AGGIORNAMENTO COMPLETATO!                      ${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "Versione: ${YELLOW}$CURRENT_VERSION${NC} → ${GREEN}$NEW_VERSION${NC}"
else
    echo -e "${RED}✗ Errore avvio servizio${NC}"
    echo "Controlla i log: journalctl -u da-pxrepl -n 50"
    exit 1
fi
