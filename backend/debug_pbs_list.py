
import asyncio
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup path and DB
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database import Node, SQLALCHEMY_DATABASE_URL
from services.pbs_service import pbs_service

async def test_pbs_listing():
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # Get DA-PBS
    node = db.query(Node).filter(Node.name == 'DA-PBS').first()
    
    if node:
        print(f"Testing PBS Node: {node.name}")
        print(f"Hostname: {node.hostname}")
        print(f"Datastore: {node.pbs_datastore}")
        print(f"User: {node.pbs_username}")
        
        # Test listing
        try:
             # Assume VMID 100 for testing or fetch from a PVE node
             print("\n--- Listing Backups for VM 100 ---")
             snaps = await pbs_service.list_backups(
                pbs_hostname=node.hostname,
                datastore=node.pbs_datastore,
                pbs_user=node.pbs_username,
                pbs_password=node.pbs_password,
                pbs_fingerprint=node.pbs_fingerprint,
                vm_id=100
             )
             print(f"Found {len(snaps)} backups.")
             print(snaps)
             
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()

    db.close()

if __name__ == "__main__":
    asyncio.run(test_pbs_listing())
