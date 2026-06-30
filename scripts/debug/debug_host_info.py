
import asyncio
import logging
import json
import os
import sys

# Setup mock env
os.environ["DAPX_DB"] = "/Users/riccardo/.dapx-unified/dapx.db"

# Add backend to path
sys.path.append("/Users/riccardo/Progetti/DA-PXREPL/dapx-unified/backend")

from database import SessionLocal, Node
from services.host_info_service import HostInfoService

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def debug_nodes():
    db = SessionLocal()
    try:
        nodes = db.query(Node).all()
        print(f"Checking {len(nodes)} nodes...")
        
        service = HostInfoService()
        
        for node in nodes:
            print(f"--- Node: {node.name} ({node.hostname}) ---")
            print(f"Status: {'Active' if node.is_active else 'Inactive'}")
            print(f"Current Host Info (DB): {json.dumps(node.host_info, indent=2) if node.host_info else 'None'}")
            print(f"Last updated: {node.host_info_updated_at}")
            
            if not node.is_active:
                print("Skipping inactive node refresh test.")
                continue

            print(f"Attempting manual refresh for {node.name}...")
            try:
                # Force refresh
                result = await service.fetch_host_details(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path,
                    include_hardware=True,
                    include_storage=True,
                    include_network=False,
                    node_type=node.node_type
                )
                print("Refresh Result Keys:", result.keys())
                print(f"CPU Info: {result.get('cpu', {}).get('model', 'Not Found')}")
                
            except Exception as e:
                print(f"Refresh FAILED: {e}")
                
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(debug_nodes())
