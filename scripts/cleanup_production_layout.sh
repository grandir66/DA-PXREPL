#!/usr/bin/env bash
# Ripulisce file legacy non tracciati da git in /opt/dapx-unified (container produzione).
# Uso: sudo bash scripts/cleanup_production_layout.sh [--dry-run]
set -euo pipefail

ROOT="${DAPX_ROOT:-/opt/dapx-unified}"
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

ARCHIVE="${ROOT}/_archive/$(date +%Y%m%d_%H%M%S)"
mkdir -p "${ARCHIVE}"

move_item() {
  local rel="$1"
  local src="${ROOT}/${rel}"
  if [[ ! -e "${src}" ]]; then
    return 0
  fi
  if git -C "${ROOT}" ls-files --error-unmatch "${rel}" >/dev/null 2>&1; then
    echo "SKIP (tracked): ${rel}"
    return 0
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "DRY-RUN move: ${rel} -> _archive/"
    return 0
  fi
  mkdir -p "${ARCHIVE}/$(dirname "${rel}")"
  mv "${src}" "${ARCHIVE}/${rel}"
  echo "MOVED: ${rel}"
}

# Backup legacy completo (pre-repo cleanup)
move_item "_legacy_backup_20260504"

# Script one-off in root (non più nel layout canonico)
for f in check_pbs_config.py check_schema.py fix_pbs_fingerprint.py manual_restore.py run_dev.py requirements.txt config.env.example; do
  move_item "${f}"
done

# Runtime scripts duplicati in root (canonici: backend/scripts/)
for f in scripts/generate_cert.py scripts/quick_diagnostic.sh scripts/verify_database.py; do
  move_item "${f}"
done

# Test duplicati in root (canonici: backend/tests/)
move_item "tests"

echo "Cleanup completato. Archivio: ${ARCHIVE}"
echo "Layout attuale: scripts/ (ops), scripts/dev/ (locale), backend/scripts/ (runtime API)"
