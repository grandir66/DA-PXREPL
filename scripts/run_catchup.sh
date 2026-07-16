#!/usr/bin/env bash
# Avvia catch-up repliche VM (tutti i gruppi attivi, force_rerun).
set -euo pipefail

LOCKFILE=/var/run/dapx-catchup.lock
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "Catch-up già in esecuzione ($LOCKFILE)" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source /etc/dapx-unified/dapx-unified.env
set +a
export PYTHONUNBUFFERED=1
exec /opt/dapx-unified/venv/bin/python3 /opt/dapx-unified/scripts/catchup_vm_groups.py
