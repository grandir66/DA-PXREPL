#!/bin/bash
#
# DAPX-Unified - Proxmox LXC Deployment Script
# Questo script va eseguito sulla shell di un host Proxmox VE
#

set -e

# ============== CONFIGURAZIONE ==============
REPO_URL="https://github.com/grandir66/DA-PXREPL.git"
APP_NAME="DAPX-Unified"
DEFAULT_HOSTNAME="dapx-unified"
DEFAULT_CORES=2
DEFAULT_MEMORY=2048
DEFAULT_SWAP=512
DEFAULT_DISK=8

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# ============== FUNZIONI UTILITÀ ==============

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_step() { echo -e "\n${BLUE}${BOLD}▶ $1${NC}"; }

print_banner() {
    clear
    echo -e "${CYAN}"
    cat << 'EOF'
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║     ██████╗  █████╗ ██████╗ ██╗  ██╗                          ║
    ║     ██╔══██╗██╔══██╗██╔══██╗╚██╗██╔╝                          ║
    ║     ██║  ██║███████║██████╔╝ ╚███╔╝                           ║
    ║     ██║  ██║██╔══██║██╔═══╝  ██╔██╗                           ║
    ║     ██████╔╝██║  ██║██║     ██╔╝ ██╗                          ║
    ║     ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝                          ║
    ║                                                               ║
    ║              U N I F I E D   v3.5                             ║
    ║                                                               ║
    ║     Backup & Replication Manager per Proxmox VE               ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    echo -e "${BOLD}   LXC Container Deployment Wizard${NC}\n"
}

# ============== VERIFICHE PRELIMINARI ==============

check_requirements() {
    log_step "Verifica requisiti"
    
    # Root check
    if [[ $EUID -ne 0 ]]; then
        log_error "Questo script deve essere eseguito come root"
        exit 1
    fi
    log_success "Esecuzione come root"
    
    # Proxmox check
    if ! command -v pct &> /dev/null; then
        log_error "Proxmox Container Tool (pct) non trovato!"
        log_error "Questo script va eseguito su un host Proxmox VE."
        exit 1
    fi
    log_success "Proxmox VE rilevato"
    
    # pvesh check
    if ! command -v pvesh &> /dev/null; then
        log_error "pvesh non trovato!"
        exit 1
    fi
    log_success "Proxmox API disponibile"
    
    # Network check
    if ! ping -c 1 github.com &>/dev/null; then
        log_error "Connessione internet non disponibile"
        exit 1
    fi
    log_success "Connessione internet OK"
}

# ============== FUNZIONI DI RACCOLTA DATI ==============

# Ottiene la lista degli storage compatibili con container
get_available_storages() {
    # Filtra solo storage che supportano rootdir (per container)
    pvesh get /storage --output-format json 2>/dev/null | \
        python3 -c "
import sys, json
data = json.load(sys.stdin)
for s in data:
    content = s.get('content', '')
    if 'rootdir' in content or 'images' in content:
        stype = s.get('type', 'unknown')
        print(f\"{s['storage']}|{stype}\")
" 2>/dev/null || echo ""
}

# Ottiene la lista dei bridge di rete
get_available_bridges() {
    # Legge i bridge dalla configurazione di rete
    ip link show type bridge 2>/dev/null | grep -oP '^\d+: \K[^:]+' | sort -u
}

# Ottiene la lista delle VLAN esistenti (se configurate)
get_existing_vlans() {
    # Cerca VLAN già configurate nel sistema
    cat /etc/network/interfaces 2>/dev/null | grep -oP 'vmbr\d+\.(\d+)' | grep -oP '\.\K\d+' | sort -u | head -20
}

# Verifica se un ID container è disponibile
is_ctid_available() {
    local ctid=$1
    if pct status $ctid &>/dev/null; then
        return 1  # Esiste già
    fi
    return 0  # Disponibile
}

# Ottiene il prossimo ID libero
get_next_free_id() {
    pvesh get /cluster/nextid 2>/dev/null || echo "100"
}

# ============== WIZARD INTERATTIVO ==============

select_from_list() {
    local prompt="$1"
    shift
    local options=("$@")
    local count=${#options[@]}
    
    if [[ $count -eq 0 ]]; then
        return 1
    fi
    
    echo ""
    echo -e "${BOLD}$prompt${NC}"
    echo ""
    
    for i in "${!options[@]}"; do
        printf "  ${CYAN}%2d)${NC} %s\n" $((i+1)) "${options[$i]}"
    done
    
    echo ""
    while true; do
        read -p "Seleziona [1-$count]: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [[ $choice -ge 1 ]] && [[ $choice -le $count ]]; then
            SELECTED_INDEX=$((choice-1))
            SELECTED_VALUE="${options[$SELECTED_INDEX]}"
            return 0
        fi
        echo -e "${RED}Selezione non valida. Riprova.${NC}"
    done
}

input_with_default() {
    local prompt="$1"
    local default="$2"
    local result
    
    read -p "$prompt [$default]: " result
    echo "${result:-$default}"
}

input_number() {
    local prompt="$1"
    local default="$2"
    local min="${3:-1}"
    local max="${4:-999999}"
    local result
    
    while true; do
        read -p "$prompt [$default]: " result
        result="${result:-$default}"
        
        if [[ "$result" =~ ^[0-9]+$ ]] && [[ $result -ge $min ]] && [[ $result -le $max ]]; then
            echo "$result"
            return 0
        fi
        echo -e "${RED}Valore non valido. Inserisci un numero tra $min e $max.${NC}"
    done
}

input_password() {
    local pass1 pass2
    
    while true; do
        read -s -p "Password root per il container: " pass1
        echo ""
        
        if [[ ${#pass1} -lt 5 ]]; then
            echo -e "${RED}La password deve essere di almeno 5 caratteri.${NC}"
            continue
        fi
        
        read -s -p "Conferma password: " pass2
        echo ""
        
        if [[ "$pass1" == "$pass2" ]]; then
            echo "$pass1"
            return 0
        fi
        echo -e "${RED}Le password non corrispondono. Riprova.${NC}"
    done
}

# ============== WIZARD PRINCIPALE ==============

run_wizard() {
    log_step "Configurazione Container"
    
    # --- 1. Container ID ---
    echo ""
    echo -e "${BOLD}1. ID Container${NC}"
    NEXT_FREE=$(get_next_free_id)
    
    while true; do
        CTID=$(input_number "   ID del container" "$NEXT_FREE" 100 999999999)
        
        if is_ctid_available "$CTID"; then
            log_success "ID $CTID disponibile"
            break
        else
            log_error "Il container $CTID esiste già!"
        fi
    done
    
    # --- 2. Hostname ---
    echo ""
    echo -e "${BOLD}2. Hostname${NC}"
    CT_HOSTNAME=$(input_with_default "   Nome host" "$DEFAULT_HOSTNAME")
    
    # Valida hostname
    if [[ ! "$CT_HOSTNAME" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$ ]]; then
        log_warn "Hostname non valido, uso default: $DEFAULT_HOSTNAME"
        CT_HOSTNAME="$DEFAULT_HOSTNAME"
    fi
    
    # --- 3. Password ---
    echo ""
    echo -e "${BOLD}3. Password Root${NC}"
    CT_PASSWORD=$(input_password)
    
    # --- 4. Storage ---
    log_step "Selezione Storage"
    
    STORAGE_LIST=()
    STORAGE_NAMES=()
    
    while IFS='|' read -r name stype; do
        if [[ -n "$name" ]]; then
            STORAGE_LIST+=("$name ($stype)")
            STORAGE_NAMES+=("$name")
        fi
    done < <(get_available_storages)
    
    if [[ ${#STORAGE_LIST[@]} -eq 0 ]]; then
        log_error "Nessuno storage compatibile trovato!"
        exit 1
    fi
    
    select_from_list "Seleziona lo storage per il disco root:" "${STORAGE_LIST[@]}"
    CT_STORAGE="${STORAGE_NAMES[$SELECTED_INDEX]}"
    log_success "Storage selezionato: $CT_STORAGE"
    
    # --- 5. Network Bridge ---
    log_step "Configurazione Rete"
    
    BRIDGE_LIST=()
    while read -r bridge; do
        if [[ -n "$bridge" ]]; then
            BRIDGE_LIST+=("$bridge")
        fi
    done < <(get_available_bridges)
    
    if [[ ${#BRIDGE_LIST[@]} -eq 0 ]]; then
        log_warn "Nessun bridge rilevato, uso vmbr0"
        BRIDGE_LIST=("vmbr0")
    fi
    
    select_from_list "Seleziona il bridge di rete:" "${BRIDGE_LIST[@]}"
    CT_BRIDGE="$SELECTED_VALUE"
    log_success "Bridge selezionato: $CT_BRIDGE"
    
    # --- 6. VLAN ---
    echo ""
    echo -e "${BOLD}VLAN Tag${NC}"
    echo "  Inserisci il VLAN tag (lascia vuoto per nessuna VLAN)"
    
    EXISTING_VLANS=$(get_existing_vlans | tr '\n' ' ')
    if [[ -n "$EXISTING_VLANS" ]]; then
        echo -e "  ${CYAN}VLAN esistenti nel sistema: $EXISTING_VLANS${NC}"
    fi
    
    read -p "  VLAN Tag [nessuna]: " CT_VLAN
    
    if [[ -n "$CT_VLAN" ]]; then
        if [[ ! "$CT_VLAN" =~ ^[0-9]+$ ]] || [[ $CT_VLAN -lt 1 ]] || [[ $CT_VLAN -gt 4094 ]]; then
            log_warn "VLAN non valida (deve essere 1-4094), ignorata"
            CT_VLAN=""
        else
            log_success "VLAN configurata: $CT_VLAN"
        fi
    fi
    
    # --- 7. IP Address ---
    echo ""
    echo -e "${BOLD}Configurazione IP${NC}"
    echo ""
    echo -e "  ${CYAN}1)${NC} DHCP (automatico)"
    echo -e "  ${CYAN}2)${NC} IP Statico"
    echo ""
    
    while true; do
        read -p "Seleziona [1-2]: " ip_choice
        case $ip_choice in
            1)
                CT_IP="dhcp"
                CT_GW=""
                log_success "Configurazione: DHCP"
                break
                ;;
            2)
                echo ""
                read -p "  Indirizzo IP (es: 192.168.1.100/24): " CT_IP
                
                # Valida formato IP/CIDR
                if [[ ! "$CT_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
                    log_error "Formato IP non valido. Usa formato: IP/CIDR (es: 192.168.1.100/24)"
                    continue
                fi
                
                read -p "  Gateway (es: 192.168.1.1): " CT_GW
                
                # Valida formato Gateway
                if [[ -n "$CT_GW" ]] && [[ ! "$CT_GW" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                    log_error "Formato Gateway non valido"
                    continue
                fi
                
                log_success "IP Statico: $CT_IP, Gateway: ${CT_GW:-nessuno}"
                break
                ;;
            *)
                echo -e "${RED}Selezione non valida.${NC}"
                ;;
        esac
    done
    
    # --- 8. Risorse Hardware ---
    log_step "Risorse Hardware"
    
    echo ""
    echo -e "${BOLD}CPU${NC}"
    CT_CORES=$(input_number "   Numero di core CPU" "$DEFAULT_CORES" 1 128)
    
    echo ""
    echo -e "${BOLD}Memoria RAM${NC}"
    CT_MEMORY=$(input_number "   RAM in MB" "$DEFAULT_MEMORY" 512 1048576)
    
    echo ""
    echo -e "${BOLD}Swap${NC}"
    CT_SWAP=$(input_number "   Swap in MB" "$DEFAULT_SWAP" 0 1048576)
    
    echo ""
    echo -e "${BOLD}Disco${NC}"
    CT_DISK=$(input_number "   Dimensione disco in GB" "$DEFAULT_DISK" 4 102400)
    
    log_success "Risorse configurate: ${CT_CORES} core, ${CT_MEMORY}MB RAM, ${CT_DISK}GB disco"
}

# ============== RIEPILOGO E CONFERMA ==============

show_summary() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}                    ${BOLD}RIEPILOGO CONFIGURAZIONE${NC}                   ${CYAN}║${NC}"
    echo -e "${CYAN}╠═══════════════════════════════════════════════════════════════╣${NC}"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "Container ID" "$CTID"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "Hostname" "$CT_HOSTNAME"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "Storage" "$CT_STORAGE"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "Disco" "${CT_DISK}GB"
    echo -e "${CYAN}╠═══════════════════════════════════════════════════════════════╣${NC}"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "Bridge" "$CT_BRIDGE"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "VLAN" "${CT_VLAN:-nessuna}"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "IP" "$CT_IP"
    [[ -n "$CT_GW" ]] && printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "Gateway" "$CT_GW"
    echo -e "${CYAN}╠═══════════════════════════════════════════════════════════════╣${NC}"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "CPU" "${CT_CORES} core"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "RAM" "${CT_MEMORY}MB"
    printf "${CYAN}║${NC}  %-20s: %-38s ${CYAN}║${NC}\n" "Swap" "${CT_SWAP}MB"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

confirm_deployment() {
    while true; do
        read -p "Procedere con il deployment? [S/n]: " confirm
        confirm="${confirm:-s}"
        case "$confirm" in
            [Ss]|[Yy]|"")
                return 0
                ;;
            [Nn])
                log_info "Deployment annullato."
                exit 0
                ;;
            *)
                echo -e "${RED}Risposta non valida.${NC}"
                ;;
        esac
    done
}

# ============== DEPLOYMENT ==============

download_template() {
    log_step "Preparazione Template"
    
    TEMPLATE_STORAGE="local"
    
    log_info "Aggiornamento lista template..."
    pveam update > /dev/null 2>&1 || true
    
    # Cerca Debian 12
    log_info "Ricerca template Debian 12..."
    TARGET_TEMPLATE=$(pveam available --section system 2>/dev/null | grep -i "debian-12-standard" | head -n 1 | awk '{print $2}')
    
    if [[ -z "$TARGET_TEMPLATE" ]]; then
        log_warn "Debian 12 non trovato, provo Debian 11..."
        TARGET_TEMPLATE=$(pveam available --section system 2>/dev/null | grep -i "debian-11-standard" | head -n 1 | awk '{print $2}')
    fi
    
    if [[ -z "$TARGET_TEMPLATE" ]]; then
        log_error "Nessun template Debian trovato!"
        exit 1
    fi
    
    log_info "Template selezionato: $TARGET_TEMPLATE"
    
    # Verifica se già scaricato
    if pveam list $TEMPLATE_STORAGE 2>/dev/null | grep -q "$TARGET_TEMPLATE"; then
        log_success "Template già presente"
    else
        log_info "Download template in corso..."
        pveam download $TEMPLATE_STORAGE "$TARGET_TEMPLATE"
        log_success "Template scaricato"
    fi
    
    TEMPLATE_VOL="$TEMPLATE_STORAGE:vztmpl/$TARGET_TEMPLATE"
}

create_container() {
    log_step "Creazione Container"
    
    # Costruisci parametri rete
    NET_CONFIG="name=eth0,bridge=$CT_BRIDGE,ip=$CT_IP"
    
    if [[ -n "$CT_GW" ]]; then
        NET_CONFIG="$NET_CONFIG,gw=$CT_GW"
    fi
    
    if [[ -n "$CT_VLAN" ]]; then
        NET_CONFIG="$NET_CONFIG,tag=$CT_VLAN"
    fi
    
    log_info "Creazione container $CTID..."
    
    pct create $CTID "$TEMPLATE_VOL" \
        --hostname "$CT_HOSTNAME" \
        --password "$CT_PASSWORD" \
        --storage "$CT_STORAGE" \
        --rootfs "$CT_STORAGE:${CT_DISK}" \
        --cores "$CT_CORES" \
        --memory "$CT_MEMORY" \
        --swap "$CT_SWAP" \
        --net0 "$NET_CONFIG" \
        --features nesting=1 \
        --ostype debian \
        --unprivileged 1 \
        --start 1
    
    log_success "Container $CTID creato e avviato"
}

wait_for_network() {
    log_step "Attesa connettività di rete"
    
    local retries=60
    echo -n "   Connessione in corso"
    
    while [[ $retries -gt 0 ]]; do
        if pct exec $CTID -- ping -c 1 8.8.8.8 &>/dev/null; then
            echo ""
            log_success "Container online"
            return 0
        fi
        echo -n "."
        sleep 2
        ((retries--))
    done
    
    echo ""
    log_error "Timeout connessione di rete"
    log_warn "Il container potrebbe non avere accesso a internet. Verifica la configurazione di rete."
    
    read -p "Continuare comunque? [s/N]: " cont
    if [[ ! "$cont" =~ ^[Ss]$ ]]; then
        exit 1
    fi
}

install_application() {
    log_step "Installazione $APP_NAME"
    
    log_info "Aggiornamento sistema..."
    pct exec $CTID -- apt-get update -qq
    
    log_info "Installazione dipendenze base..."
    pct exec $CTID -- apt-get install -y -qq git curl wget
    
    log_info "Clone repository..."
    pct exec $CTID -- rm -rf /opt/dapx-unified
    pct exec $CTID -- git clone --quiet "$REPO_URL" /opt/dapx-unified
    
    log_info "Esecuzione installer (questa operazione richiede alcuni minuti)..."
    pct exec $CTID -- bash -c "cd /opt/dapx-unified && chmod +x install.sh && NONINTERACTIVE=true ./install.sh --local"
    
    log_success "Installazione completata"
}

show_completion() {
    # Ottieni IP del container
    local CT_FINAL_IP=""
    
    if [[ "$CT_IP" == "dhcp" ]]; then
        CT_FINAL_IP=$(pct exec $CTID -- hostname -I 2>/dev/null | awk '{print $1}')
    else
        CT_FINAL_IP=$(echo "$CT_IP" | cut -d'/' -f1)
    fi
    
    local PORT=8420
    
    echo ""
    echo -e "${GREEN}"
    cat << 'EOF'
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║         ✓ DEPLOYMENT COMPLETATO CON SUCCESSO!                 ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    echo -e "${BOLD}Accedi all'interfaccia web:${NC}"
    echo ""
    if [[ -n "$CT_FINAL_IP" ]]; then
        echo -e "    ${GREEN}➜${NC}  http://${CT_FINAL_IP}:${PORT}"
    else
        echo -e "    ${YELLOW}➜${NC}  http://<IP-CONTAINER>:${PORT}"
        echo -e "    ${CYAN}   Verifica IP con: pct exec $CTID -- hostname -I${NC}"
    fi
    echo ""
    
    echo -e "${BOLD}Primo accesso:${NC}"
    echo ""
    echo -e "    1. Apri il browser all'indirizzo sopra"
    echo -e "    2. Usa le credenziali Proxmox per accedere"
    echo -e "    3. Configura i nodi e i job di replica"
    echo ""
    
    echo -e "${BOLD}Comandi utili:${NC}"
    echo ""
    echo -e "    Accedi al container:    ${CYAN}pct enter $CTID${NC}"
    echo -e "    Stato servizio:         ${CYAN}pct exec $CTID -- systemctl status dapx-unified${NC}"
    echo -e "    Log applicazione:       ${CYAN}pct exec $CTID -- journalctl -u dapx-unified -f${NC}"
    echo ""
}

# ============== MAIN ==============

main() {
    print_banner
    check_requirements
    run_wizard
    show_summary
    confirm_deployment
    download_template
    create_container
    wait_for_network
    install_application
    show_completion
}

# Entry point
main "$@"
