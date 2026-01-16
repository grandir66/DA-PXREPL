#!/bin/bash
# ----------------------------------------------------------------------
# SCRIPT DI DEPLOY PARALLELO PER FEATURE BRANCH (BETA/TESTING)
# Permette di eseguire una seconda istanza di DA-PXREPL su una porta diversa
# mantenendo attiva e sicura l'istanza di produzione.
# ----------------------------------------------------------------------

# --- CONFIGURAZIONE ---
# Directory dove installare la versione Beta
BETA_DIR="/opt/dapx-beta"

# Porta su cui esporre la Beta (Default 8420 è occupata dalla Prod)
PORT="8421"

# Branch da deployare
REPO_URL="https://github.com/grandir66/DA-PXREPL.git"
BRANCH="feature/load-balancer"

# Nome del servizio Systemd per la Beta
SERVICE_NAME="dapx-beta"

# Percorsi Database
# PROD_DB: Path del database di produzione attuale (da copiare)
# BETA_DB: Path del nuovo database separato per la Beta
PROD_DB="/var/lib/dapx-unified/dapx.db"
BETA_DB="/var/lib/dapx-unified/dapx-beta.db"

# Rilevamento privilegi
SUDO=""
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
fi

# ----------------------------------------------------------------------

echo "================================================================"
echo "   🚀 DA-PXREPL - Deploy Parallelo Feature Branch ($BRANCH)"
echo "   Porta: $PORT | Service: $SERVICE_NAME"
echo "================================================================"

# 1. Verifica Prerequisiti
if ! command -v git &> /dev/null; then echo "❌ Errore: git non installato"; exit 1; fi
if ! command -v python3 &> /dev/null; then echo "❌ Errore: python3 non installato"; exit 1; fi
if ! command -v npm &> /dev/null; then echo "❌ Errore: npm non installato"; exit 1; fi

# 2. Preparazione Directory
echo "📂 Preparazione directory $BETA_DIR..."
if [ -d "$BETA_DIR" ]; then
    echo "   Aggiornamento sorgenti esistenti..."
    cd "$BETA_DIR"
    $SUDO git fetch origin
    $SUDO git checkout "$BRANCH"
    $SUDO git pull origin "$BRANCH"
else
    echo "   Clonazione repository..."
    $SUDO git clone -b "$BRANCH" "$REPO_URL" "$BETA_DIR"
    cd "$BETA_DIR"
fi

# Fix ownership se creato con sudo
$SUDO chown -R $USER:$GROUPS "$BETA_DIR"

# 3. Setup Ambiente Python
echo "🐍 Configurazione ambiente Python (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
echo "   Installazione dipendenze..."
pip install -r backend/requirements.txt --upgrade --quiet

# 4. Compilazione Frontend
echo "🎨 Compilazione Frontend..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "   Installazione dipendenze NPM..."
    npm install --silent
fi
echo "   Building..."
npm run build --silent
cd ..

# 5. Configurazione Database Isolato
echo "💾 Configurazione Database..."
if [ ! -f "$BETA_DB" ]; then
    if [ -f "$PROD_DB" ]; then
        if command -v sqlite3 &> /dev/null; then
             echo "   Esecuzione Hot Backup SQLite (safe)..."
             sqlite3 "$PROD_DB" ".backup '$BETA_DB'"
        else
             echo "⚠️  sqlite3 non trovato. Esecuzione copia raw (potrebbe richiedere lock)..."
             $SUDO cp "$PROD_DB" "$BETA_DB"
        fi
        
        # Disattivazione job per evitare conflitti
        if command -v sqlite3 &> /dev/null; then
            echo "   ⏸️  Disattivazione Job schedulati nel DB Beta per sicurezza..."
            sqlite3 "$BETA_DB" "UPDATE sync_jobs SET is_active=0; UPDATE recovery_jobs SET is_active=0; UPDATE backup_jobs SET is_active=0; UPDATE migration_jobs SET is_active=0; UPDATE host_backup_jobs SET is_active=0;"
        else
            echo "⚠️  Impossibile disattivare i job (sqlite3 mancate). Disattivali manualmente dalla UI Beta!"
        fi
        
        $SUDO chown root:root "$BETA_DB"
    else
        echo "⚠️  DB Produzione non trovato in $PROD_DB. Verrà creato un nuovo DB vuoto."
    fi
else
    echo "   Database Beta esistente trovato. Mantenimento dati attuali."
fi

# 6. Creazione/Aggiornamento Servizio Systemd
echo "⚙️  Configurazione Systemd ($SERVICE_NAME)..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Config directory specifica per la beta
CONFIG_DIR="$BETA_DIR/config"
LOG_DIR="$BETA_DIR/logs"
mkdir -p "$CONFIG_DIR"
mkdir -p "$LOG_DIR"

$SUDO tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=DA-PXREPL Beta ($BRANCH)
After=network.target

[Service]
User=root
WorkingDirectory=$BETA_DIR
Environment="PATH=$BETA_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="SANOID_MANAGER_PORT=$PORT"
Environment="DAPX_DB=$BETA_DB"
Environment="DAPX_CONFIG_DIR=$CONFIG_DIR"
Environment="DAPX_LOG_DIR=$LOG_DIR"
ExecStart=$BETA_DIR/venv/bin/python backend/main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 7. Avvio Servizio
echo "🚀 Avvio servizio..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable "$SERVICE_NAME"
$SUDO systemctl restart "$SERVICE_NAME"

# check status
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✅ DEPLOY COMPLETATO CON SUCCESSO!"
    echo "----------------------------------------------------------------"
    echo "   La nuova versione è accessibile su:"
    echo "   http://<IP-SERVER>:$PORT"
    echo "----------------------------------------------------------------"
else
    echo "❌ Errore nell'avvio del servizio. Controlla: journalctl -u $SERVICE_NAME -f"
fi
