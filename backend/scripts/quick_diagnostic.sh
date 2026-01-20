#!/bin/bash
#
# QuickDiagnostic.sh
#
# Performs quick system diagnostics checking storage, memory, CPU, network, and logs.
# Provides a summary of any critical issues or warnings.
#
# STANDALONE VERSION: No external dependencies required.
#

set -euo pipefail

# --- Utility Functions (Embedded) -------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

__info__() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

__ok__() {
    echo -e "${GREEN}[OK]${NC}   $1"
}

__warn__() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

__err__() {
    echo -e "${RED}[ERR]${NC}  $1"
}

__check_root__() {
    if [[ $EUID -ne 0 ]]; then
        __err__ "This script must be run as root"
        exit 1
    fi
}

__check_proxmox__() {
    if [[ ! -f /etc/pve/storage.cfg ]]; then
        __warn__ "Not running on a standard Proxmox VE host (missing /etc/pve/storage.cfg)"
    fi
}

# --- check_storage_errors ----------------------------------------------------
check_storage_errors() {
    __info__ "Checking storage..."

    local issues=0

    # Check ZFS
    if command -v zpool &>/dev/null; then
        local zpool_status
        zpool_status=$(zpool status 2>/dev/null | grep -i 'FAULTED\|DEGRADED' || true)
        if [[ -n "$zpool_status" ]]; then
            __warn__ "ZFS issues detected:"
            echo "$zpool_status"
            issues=$((issues + 1))
        fi
    fi

    # Check Ceph
    if command -v ceph &>/dev/null; then
        local ceph_status
        ceph_status=$(ceph health 2>/dev/null | grep -i 'HEALTH_ERR\|HEALTH_WARN' || true)
        if [[ -n "$ceph_status" ]]; then
            __warn__ "Ceph issues detected:"
            echo "$ceph_status"
            issues=$((issues + 1))
        fi
    fi

    # Check storage usage
    local storage_usage
    storage_usage=$(df -h | awk '$5+0 > 90 {print "  " $6 " is " $5 " full"}')
    if [[ -n "$storage_usage" ]]; then
        __warn__ "High storage usage:"
        echo "$storage_usage"
        issues=$((issues + 1))
    fi

    # Check LVM locks
    if command -v lvs &>/dev/null; then
        local locked_storage
        locked_storage=$(lvs -o+lock_args 2>/dev/null | grep -i 'lock' || true)
        if [[ -n "$locked_storage" ]]; then
            __warn__ "Locked storage detected:"
            echo "$locked_storage"
            issues=$((issues + 1))
        fi
    fi

    [[ $issues -eq 0 ]] && __ok__ "Storage: OK"
}

# --- check_memory_errors -----------------------------------------------------
check_memory_errors() {
    __info__ "Checking memory..."

    local issues=0

    # Check for memory errors in dmesg
    local memory_errors
    memory_errors=$(dmesg | grep -iE 'memory error|out of memory|oom-killer' || true)
    if [[ -n "$memory_errors" ]]; then
        __warn__ "Memory errors detected in dmesg"
        issues=$((issues + 1))
    fi

    # Check memory usage
    local memory_usage
    memory_usage=$(free -m | awk '/Mem:/ {if ($3/$2 * 100 > 90) printf "  Memory usage: %.1f%%\n", ($3/$2 * 100)}')
    if [[ -n "$memory_usage" ]]; then
        __warn__ "High memory usage:"
        echo "$memory_usage"
        ps -eo pid,cmd,%mem --sort=-%mem | head -n 6
        issues=$((issues + 1))
    fi

    [[ $issues -eq 0 ]] && __ok__ "Memory: OK"
}

# --- check_cpu_errors --------------------------------------------------------
check_cpu_errors() {
    __info__ "Checking CPU..."

    local issues=0

    # Check for CPU errors in dmesg
    local cpu_errors
    cpu_errors=$(dmesg | grep -iE 'cpu error|thermal throttling|overheating' || true)
    if [[ -n "$cpu_errors" ]]; then
        __warn__ "CPU errors detected in dmesg"
        issues=$((issues + 1))
    fi

    # Check CPU usage
    local cpu_usage
    cpu_usage=$(top -bn1 | awk '/^%Cpu/ {if ($2 > 90) print "  CPU usage: " $2 "%"}')
    if [[ -n "$cpu_usage" ]]; then
        __warn__ "High CPU usage:"
        echo "$cpu_usage"
        ps -eo pid,cmd,%cpu --sort=-%cpu | head -n 6
        issues=$((issues + 1))
    fi

    [[ $issues -eq 0 ]] && __ok__ "CPU: OK"
}

# --- check_network_errors ----------------------------------------------------
check_network_errors() {
    __info__ "Checking network..."

    local network_errors
    network_errors=$(dmesg | grep -iE 'network error|link is down|nic error|carrier lost' || true)
    if [[ -n "$network_errors" ]]; then
        __warn__ "Network errors detected (dmesg):"
        echo "$network_errors" | tail -5
    else
        __ok__ "Network: OK"
    fi
}

# --- check_system_log_errors -------------------------------------------------
check_system_log_errors() {
    __info__ "Checking system logs..."

    if command -v journalctl &>/dev/null; then
        local syslog_errors
        syslog_errors=$(journalctl -p err -b --no-pager | tail -10)
        if [[ -n "$syslog_errors" ]]; then
            __warn__ "Recent errors in system logs:"
            echo "$syslog_errors"
        else
            __ok__ "System logs: OK"
        fi
    else
        __warn__ "journalctl not available"
    fi
}

# --- main --------------------------------------------------------------------
main() {
    __check_root__
    __check_proxmox__

    echo
    __info__ "Starting Quick Diagnostic..."
    echo "---------------------------------------------------"

    check_storage_errors
    check_memory_errors
    check_cpu_errors
    check_network_errors
    check_system_log_errors

    echo "---------------------------------------------------"
    __ok__ "Diagnostic completed."
    echo
}

main
