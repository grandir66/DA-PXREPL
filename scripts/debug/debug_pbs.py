
import asyncio
import os
import sys
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, Node, SQLALCHEMY_DATABASE_URL
from services.ssh_service import ssh_service

# Setup DB
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

async def test_pbs_listing():
    db = SessionLocal()
    try:
        nodes = db.query(Node).all()
        if not nodes:

            print("No nodes found in DB")
            return

        print(f"Found {len(nodes)} nodes in DB.")
        
        # Test VMID 100 for example
        TEST_VMID = 100 
        
        for node in nodes:
            print(f"\n--- Checking Node: {node.name} ({node.hostname}) [Type: {node.node_type}] ---")
            
            # CASE A: PVE Node - check storage
            if node.node_type == 'pve' or not node.node_type:
                cmd = "pvesh get /storage --output-format json"
                print(f"  [PVE] Executing: {cmd}")
                result = await ssh_service.execute(node.hostname, cmd, node.ssh_port, node.ssh_user, node.ssh_key_path)
                
                if result.success:
                    try:
                        storages = json.loads(result.stdout)
                        pbs_storages = [s for s in storages if s.get("type") == "pbs" and s.get("active") == 1]
                        print(f"    Found {len(pbs_storages)} Active PBS storages via PVE.")
                    except:
                        pass
                else:
                    print(f"    PVE Command failed: {result.stderr}")

            # CASE B: PBS Node - check direct manager
            if node.node_type == 'pbs':
                datastore = node.pbs_datastore or "backup" # Default fallback
                print(f"  [PBS] Checking datastore '{datastore}' for vm/{TEST_VMID}...")
                
                # Command: proxmox-backup-manager snapshot list --datastore <store> --group vm/<vmid> --output-format json
                cmd_pbs = f"proxmox-backup-manager snapshot list --datastore {datastore} --group vm/{TEST_VMID} --output-format json"
                print(f"  [PBS] Executing: {cmd_pbs}")
                
                res_pbs = await ssh_service.execute(node.hostname, cmd_pbs, node.ssh_port, node.ssh_user, node.ssh_key_path)
                
                if res_pbs.success:
                    print(f"    Success! Output: {res_pbs.stdout[:200]}...")
                    try:
                        snaps = json.loads(res_pbs.stdout)
                        print(f"    Found {len(snaps)} snapshots directly on PBS.")
                    except:
                        print("    Failed to parse JSON.")
                else:
                    print(f"    PBS Command failed: {res_pbs.stderr}")
                
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_pbs_listing())
