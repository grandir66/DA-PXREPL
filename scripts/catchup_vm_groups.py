#!/usr/bin/env python3
"""Esegue in sequenza tutti i gruppi VM attivi (force_rerun) per recupero manuale."""
import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from database import SessionLocal, SyncJob  # noqa: E402
from routers.sync_jobs import execute_vm_group_sync_task  # noqa: E402


async def main() -> int:
    db = SessionLocal()
    try:
        groups = [
            row[0]
            for row in db.query(SyncJob.vm_group_id)
            .filter(
                SyncJob.is_active == True,  # noqa: E712
                SyncJob.vm_group_id.isnot(None),
            )
            .distinct()
            .all()
            if row[0]
        ]
    finally:
        db.close()

    if not groups:
        print("Nessun gruppo VM attivo.")
        return 0

    print(f"Catch-up: {len(groups)} gruppi VM")
    for gid in groups:
        print(f"--- {gid} ---")
        await execute_vm_group_sync_task(gid, force_rerun=True)
        print(f"--- {gid} done ---")

    print("Catch-up completato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
