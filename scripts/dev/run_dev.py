#!/usr/bin/env python3
"""Avvia uvicorn in locale (sviluppo). Eseguire dalla root repo:
  python3 scripts/dev/run_dev.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    base_dir = os.path.expanduser("~/.dapx-unified")
    os.environ.setdefault("DAPX_DATA_DIR", base_dir)
    os.environ.setdefault("DAPX_CONFIG_DIR", os.path.join(base_dir, "config"))
    os.environ.setdefault("DAPX_LOG_DIR", os.path.join(base_dir, "logs"))
    os.environ.setdefault("DAPX_Install_DIR", str(BACKEND.parent))

    for sub in ("", "config", "logs", "backups"):
        os.makedirs(os.path.join(base_dir, sub) if sub else base_dir, exist_ok=True)

    print(f"Backend: {BACKEND}")
    print(f"DATA_DIR: {os.environ['DAPX_DATA_DIR']}")
    uvicorn.run("main:app", host="0.0.0.0", port=8420, reload=True)
