#!/usr/bin/env python3
"""Ripara ExecStart systemd dopo update (venv + SSL opzionale)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.dapx_systemd import load_server_config, service_access_url, sync_systemd_unit


def main() -> int:
    config = load_server_config()
    if not sync_systemd_unit(config):
        print("WARN: unit systemd non aggiornato", file=sys.stderr)
        return 1
    print(f"OK: {service_access_url(config)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
