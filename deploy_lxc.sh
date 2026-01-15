#!/bin/bash
#
# Deploy DAPX-Unified in a Proxmox LXC Container
# This script must be run on a Proxmox VE Host
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Defaults
REPO_URL="https://github.com/grandir66/DA-PXREPL.git"
DEFAULT_HOSTNAME="dapx-unified"
DEFAULT_CORES=2
DEFAULT_MEMORY=2048
DEFAULT_SWAP=512
DEFAULT_DISK=8
DEFAULT_BRIDGE="vmbr0"
DEFAULT_STORAGE="local-lvm"

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# Check execution environment
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root"
   exit 1
fi

if ! command -v pct &> /dev/null; then
    log_error "Proxmox Container Tool (pct) not found. Are you running this on a Proxmox VE host?"
    exit 1
fi

# Detect next free ID
NEXT_ID=$(pvesh get /cluster/nextid)

# --- Wizard ---

echo -e "\n${GREEN}=== DAPX-Unified LXC Deployment Wizard ===${NC}\n"

# 1. Container ID
read -p "Container ID [$NEXT_ID]: " CTID
CTID=${CTID:-$NEXT_ID}

# Check if ID exists
if pct status $CTID &>/dev/null; then
    log_error "Container $CTID already exists!"
    exit 1
fi

# 2. Hostname
read -p "Hostname [$DEFAULT_HOSTNAME]: " CT_HOSTNAME
CT_HOSTNAME=${CT_HOSTNAME:-$DEFAULT_HOSTNAME}

# 3. Password
while true; do
    read -s -p "Root Password: " PASSWORD
    echo
    read -s -p "Confirm Password: " PASSWORD_CONFIRM
    echo
    [ "$PASSWORD" = "$PASSWORD_CONFIRM" ] && break
    log_chain "Passwords do not match. Try again."
done

# 4. Storage selection
echo -e "\nAvailable Storage:"
pvesh get /storage --output-format text --noborder 1 | awk '{print " - " $1 " (" $2 ")"}'
read -p "Target Storage for Root Disk [$DEFAULT_STORAGE]: " STORAGE
STORAGE=${STORAGE:-$DEFAULT_STORAGE}

# 5. Network
read -p "Network Bridge [$DEFAULT_BRIDGE]: " BRIDGE
BRIDGE=${BRIDGE:-$DEFAULT_BRIDGE}

read -p "VLAN Tag (empty for none): " VLAN
VLAN_CMD=""
if [[ -n "$VLAN" ]]; then
    VLAN_CMD=",tag=$VLAN"
fi

read -p "IPv4 Address (CIDR) [dhcp]: " IP
IP=${IP:-dhcp}

GW_CMD=""
if [[ "$IP" != "dhcp" ]]; then
    read -p "Gateway IP: " GW
    if [[ -n "$GW" ]]; then
        GW_CMD=",gw=$GW"
    fi
fi

# 6. Resources
echo -e "\n--- Resource Allocation ---"
read -p "CPU Cores [$DEFAULT_CORES]: " CORES
CORES=${CORES:-$DEFAULT_CORES}

read -p "Memory (MB) [$DEFAULT_MEMORY]: " MEMORY
MEMORY=${MEMORY:-$DEFAULT_MEMORY}

read -p "Swap (MB) [$DEFAULT_SWAP]: " SWAP
SWAP=${SWAP:-$DEFAULT_SWAP}

read -p "Disk Size (GB) [$DEFAULT_DISK]: " DISK
DISK=${DISK:-$DEFAULT_DISK}

# --- Deployment ---

echo -e "\n${CYAN}Summary:${NC}"
echo "  ID:       $CTID"
echo "  Hostname: $CT_HOSTNAME"
echo "  Storage:  $STORAGE (${DISK}GB)"
echo "  Network:  $BRIDGE (VLAN: ${VLAN:-none}, IP: $IP)"
echo "  Res:      ${CORES} cores, ${MEMORY}MB RAM"
echo ""
read -p "Proceed with deployment? [Y/n] " PROCEED
if [[ "$PROCEED" =~ ^[Nn]$ ]]; then
    exit 0
fi

# Template Handling (Debian 12)
TEMPLATE="debian-12-standard"
TEMPLATE_FILE=""

log_info "Checking for Debian 12 template..."
# Try to find a local template
TEMPLATE_LIST=$(pveam available | grep "$TEMPLATE")
if [[ -z "$TEMPLATE_LIST" ]]; then
    log_warn "Debian 12 template not found in available list. Falling back to Debian 11 or latest."
    TEMPLATE="debian-11-standard"
fi

# Download if not present
# Assuming local storage 'local' usually holds templates
TEMPLATE_STORAGE="local"
log_info "Ensuring template exists on $TEMPLATE_STORAGE..."
pveam update > /dev/null

# Find the exact template name from available
TARGET_TEMPLATE=$(pveam available --section system | grep "$TEMPLATE" | head -n 1 | awk '{print $2}')

if [[ -z "$TARGET_TEMPLATE" ]]; then
    log_error "Could not find a suitable Debian template."
    exit 1
fi

log_info "Selected template: $TARGET_TEMPLATE"

# Check if already downloaded
if ! pveam list $TEMPLATE_STORAGE | grep -q "$TARGET_TEMPLATE"; then
    log_info "Downloading template..."
    pveam download $TEMPLATE_STORAGE "$TARGET_TEMPLATE"
fi

TEMPLATE_VOL="$TEMPLATE_STORAGE:vztmpl/$TARGET_TEMPLATE"

# Create Container
log_info "Creating Container $CTID..."

pct create $CTID "$TEMPLATE_VOL" \
    --hostname "$CT_HOSTNAME" \
    --password "$PASSWORD" \
    --storage "$STORAGE" \
    --rootfs "$STORAGE:${DISK}" \
    --cores "$CORES" \
    --memory "$MEMORY" \
    --swap "$SWAP" \
    --net0 "name=eth0,bridge=$BRIDGE,ip=$IP$GW_CMD$VLAN_CMD" \
    --features nesting=1 \
    --ostype debian \
    --unprivileged 1 \
    --start 1

log_success "Container created and started."

# Wait for network
log_info "Waiting for network connectivity in container..."
for i in {1..30}; do
    if pct exec $CTID -- ping -c 1 8.8.8.8 &>/dev/null; then
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

# Bootstrap Installation
log_info "Bootstrapping DAPX-Unified installation..."

# Install basic deps
pct exec $CTID -- apt-get update
pct exec $CTID -- apt-get install -y git curl

# Clone Repo
log_info "Cloning repository..."
pct exec $CTID -- rm -rf /opt/dapx-unified
pct exec $CTID -- git clone "$REPO_URL" /opt/dapx-unified

# Run Install
log_info "Running installer inside container..."
pct exec $CTID -- bash -c "cd /opt/dapx-unified && chmod +x install.sh && NONINTERACTIVE=true ./install.sh --local"

# Show connection info
PCT_IP=$(pct exec $CTID -- hostname -I | awk '{print $1}')
PORT=8420

echo -e "\n${GREEN}==============================================${NC}"
echo -e "${GREEN}   Deployment Complete!${NC}"
echo -e "${GREEN}==============================================${NC}"
echo ""
echo -e "Access the web interface at:"
if [[ "$IP" == "dhcp" ]]; then
    echo -e "  http://${PCT_IP}:${PORT}"
else
    # Remove CIDR
    CLEAN_IP=$(echo $IP | cut -d'/' -f1)
    echo -e "  http://${CLEAN_IP}:${PORT}"
fi
echo ""
echo -e "Default credentials: setup your admin user on first login."
echo ""
