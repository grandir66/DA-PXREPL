#!/usr/bin/env python3
"""One-off: reset failed disks in VM404 group and re-run group sync."""
import asyncio
import sqlite3

from routers.sync_jobs import execute_vm_group_sync_task

VM_GROUP_ID = "02bc9b0f"

conn = sqlite3.connect("/var/lib/dapx-unified/dapx.db")
cur = conn.execute(
    """
    UPDATE sync_jobs
    SET last_status = NULL, current_status = 'idle'
    WHERE vm_group_id = ? AND last_status = 'failed'
    """,
    (VM_GROUP_ID,),
)
conn.commit()
print(f"reset {cur.rowcount} failed job(s) in group {VM_GROUP_ID}")

asyncio.run(execute_vm_group_sync_task(VM_GROUP_ID))
print("group sync task finished")
