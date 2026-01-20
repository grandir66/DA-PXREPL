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

    # Check LVM locks (skip header, look for actual lock values)
    if command -v lvs &>/dev/null; then
        local locked_storage
        # Use --noheadings to skip column headers, check if any LV has non-empty lock_args
        locked_storage=$(lvs --noheadings -o lv_name,vg_name,lock_args 2>/dev/null | awk '$3 != "" {print}' || true)
        if [[ -n "$locked_storage" ]]; then
            __warn__ "Locked storage detected:"
            echo "$locked_storage"
            issues=$((issues + 1))
        fi
    fi

    if [[ $issues -eq 0 ]]; then
        __ok__ "Storage: OK"
    else
        WARNINGS_COUNT=$((WARNINGS_COUNT + issues))
    fi
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

    if [[ $issues -eq 0 ]]; then
        __ok__ "Memory: OK"
    else
        WARNINGS_COUNT=$((WARNINGS_COUNT + issues))
    fi
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

    if [[ $issues -eq 0 ]]; then
        __ok__ "CPU: OK"
    else
        WARNINGS_COUNT=$((WARNINGS_COUNT + issues))
    fi
}

# --- check_network_errors ----------------------------------------------------
check_network_errors() {
    __info__ "Checking network..."

    local issues=0
    
    # Check current interface states (live status, not old dmesg)
    if command -v ip &>/dev/null; then
        local down_interfaces
        down_interfaces=$(ip link show | grep -E 'state DOWN' | grep -vE 'lo:|docker|veth|tap|fwbr|fwpr|fwln' | awk -F: '{print $2}' | tr -d ' ' || true)
        if [[ -n "$down_interfaces" ]]; then
            __warn__ "Interfaces currently DOWN:"
            echo "$down_interfaces" | while read iface; do
                echo "  • $iface"
            done
            issues=$((issues + 1))
        fi
    fi
    
    # Check for very recent network errors only (last 10 minutes)
    if command -v journalctl &>/dev/null; then
        local recent_network_errors
        recent_network_errors=$(journalctl --since "10 minutes ago" -p warning --no-pager 2>/dev/null | grep -iE 'link is down|carrier lost|nic error' | tail -3 || true)
        if [[ -n "$recent_network_errors" ]]; then
            __warn__ "Recent network events (last 10 min):"
            echo "$recent_network_errors"
            issues=$((issues + 1))
        fi
    fi
    
    if [[ $issues -eq 0 ]]; then
        __ok__ "Network: OK"
    else
        WARNINGS_COUNT=$((WARNINGS_COUNT + issues))
    fi
}

# --- check_system_log_errors -------------------------------------------------
check_system_log_errors() {
    __info__ "Checking system logs..."

    if command -v journalctl &>/dev/null; then
        local syslog_errors
        # Filter out common non-critical errors:
        # - pvescheduler backup errors for missing VMs (scheduled jobs for removed VMs)
        # - authentication failures (handled separately or not critical for diagnostics)
        # - qga timeout (guest agent not installed, not critical)
        syslog_errors=$(journalctl -p err --since "1 hour ago" --no-pager 2>/dev/null \
            | grep -vE 'pvescheduler.*unable to find VM|authentication failure|qga command.*timeout' \
            | tail -10 || true)
        
        if [[ -n "$syslog_errors" ]] && [[ $(echo "$syslog_errors" | grep -c .) -gt 1 ]]; then
            __warn__ "Critical errors in system logs (last 1h):"
            echo "$syslog_errors"
            WARNINGS_COUNT=$((WARNINGS_COUNT + 1))
        else
            __ok__ "System logs: OK (no critical errors)"
        fi
    else
        __warn__ "journalctl not available"
        WARNINGS_COUNT=$((WARNINGS_COUNT + 1))
    fi
}

# --- Counters for summary -----------------------------------------------------
ISSUES_COUNT=0
WARNINGS_COUNT=0

# --- main --------------------------------------------------------------------
main() {
    __check_root__
    __check_proxmox__

    local start_time=$(date +%s)
    local hostname=$(hostname)
    
    echo
    echo "╔═══════════════════════════════════════════════════════════════════╗"
    echo "║                    📋 QUICK DIAGNOSTIC REPORT                    ║"
    echo "╠═══════════════════════════════════════════════════════════════════╣"
    echo "║  Host: $(printf '%-58s' "$hostname")║"
    echo "║  Date: $(printf '%-58s' "$(date '+%Y-%m-%d %H:%M:%S')")║"
    echo "╚═══════════════════════════════════════════════════════════════════╝"
    echo

    check_storage_errors
    echo
    check_memory_errors
    echo
    check_cpu_errors
    echo
    check_network_errors
    echo
    check_system_log_errors

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    echo
    echo "╔═══════════════════════════════════════════════════════════════════╗"
    echo "║                         📊 SUMMARY                               ║"
    echo "╠═══════════════════════════════════════════════════════════════════╣"
    
    # Check results and build summary
    local status_icon="✅"
    local status_text="All checks passed"
    local status_color="${GREEN}"
    
    if [[ $ISSUES_COUNT -gt 0 ]]; then
        status_icon="❌"
        status_text="$ISSUES_COUNT issue(s) detected"
        status_color="${RED}"
    elif [[ $WARNINGS_COUNT -gt 0 ]]; then
        status_icon="⚠️"
        status_text="$WARNINGS_COUNT warning(s) detected"
        status_color="${YELLOW}"
    fi
    
    echo -e "║  Status: ${status_color}${status_icon} ${status_text}${NC}$(printf '%*s' $((42 - ${#status_text})) '')║"
    echo "║  Duration: ${duration}s$(printf '%*s' 54 '')║"
    echo "╚═══════════════════════════════════════════════════════════════════╝"
    echo
}

main
