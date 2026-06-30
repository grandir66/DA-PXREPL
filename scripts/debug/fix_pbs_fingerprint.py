
import asyncio
import logging
import sys
import os

sys.path.append(os.getcwd())

from database import SessionLocal, Node, NodeType
from services.pbs_service import pbs_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_fingerprints():
    db = SessionLocal()
    try:
        pbs_nodes = db.query(Node).filter(Node.node_type == NodeType.PBS.value).all()
        for node in pbs_nodes:
            print(f"Checking node {node.name}...")
            if node.pbs_username and node.pbs_password:
                if not node.pbs_fingerprint:
                    print(f"  -> Missing fingerprint. Fetching...")
                    fp = await pbs_service.get_fingerprint(
                        hostname=node.hostname,
                        port=node.ssh_port,
                        username=node.ssh_user,
                        key_path=node.ssh_key_path
                    )
                    if fp:
                        print(f"  -> Found: {fp}")
                        node.pbs_fingerprint = fp
                        db.commit()
                        print("  -> Saved to DB.")
                    else:
                        print("  -> Failed to fetch fingerprint.")
                else:
                    print(f"  -> Fingerprint already present: {node.pbs_fingerprint[:20]}...")
            else:
                print("  -> Partial credentials (no user/pass). Skipping.")
                
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(fix_fingerprints())
