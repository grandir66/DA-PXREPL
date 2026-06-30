import asyncio
import json
import logging
import sys
import os

# Adjust path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, Node, NodeType
from services.pbs_service import pbs_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    db = SessionLocal()
    try:
        # Find PBS node
        pbs_node = db.query(Node).filter(Node.node_type == NodeType.PBS.value, Node.is_active == True).first()
        if not pbs_node:
            print("No PBS node found.")
            return

        print(f"PBS Node: {pbs_node.name} ({pbs_node.hostname})")
        print(f"Datastore: {pbs_node.pbs_datastore}")
        print(f"User: {pbs_node.pbs_username}")

        # Fetch ALL snapshots/backups without filtering by VMID
        try:
            # We call list_backups_api but manually - we want raw access
            # Or we can reuse list_backups_api passing vm_id=None if supported (it is!)
            backups = await pbs_service.list_backups_api(
                pbs_hostname=pbs_node.hostname,
                datastore=pbs_node.pbs_datastore,
                pbs_user=pbs_node.pbs_username or "root@pam",
                pbs_password=pbs_node.pbs_password,
                vm_id=None # Fetch ALL
            )
            
            print(f"\n--- Found {len(backups)} Total Backups ---")
            
            # Group by backup-id to see what VMs have backups
            backup_counts = {}
            for b in backups:
                bid = b.get('backup-id')
                btype = b.get('backup-type')
                key = f"{btype}/{bid}"
                if key not in backup_counts:
                    backup_counts[key] = 0
                backup_counts[key] += 1
                
            print("\n--- Backup Counts per Object ---")
            for k, v in sorted(backup_counts.items()):
                print(f"{k}: {v} backups")
                
        except Exception as e:
            print(f"Error fetching backups: {e}")
            import traceback
            traceback.print_exc()

    finally:
        db.close()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
