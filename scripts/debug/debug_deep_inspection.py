
import asyncio
import logging
import json
import sys
import os

# Aggiungi path corrente per importare moduli backend
sys.path.append(os.getcwd())

from database import SessionLocal, Node, NodeType
from services.pbs_service import pbs_service
from services.ssh_service import ssh_service
from services.proxmox_service import proxmox_service

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def debug_inspection():
    db = SessionLocal()
    try:
        print("=== 1. LISTA NODI PVE & VM ===")
        pve_nodes = db.query(Node).filter(Node.node_type == 'pve').all()
        first_vm = None
        first_pve = None
        
        for node in pve_nodes:
            print(f"Node: {node.name} ({node.hostname})")
            if not node.is_online:
                print("  -> OFFLINE (skipping)")
                continue
                
            try:
                vms = await proxmox_service.get_all_guests(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path
                )
                print(f"  -> Found {len(vms)} VMs/CTs")
                for vm in vms[:5]: # Show first 5
                    print(f"     - {vm['vmid']}: {vm.get('name')} ({vm.get('status')})")
                    if not first_vm:
                        first_vm = vm
                        first_pve = node
            except Exception as e:
                print(f"  -> Error listing VMs: {e}")

        print("\n=== 2. RAW SNAPSHOTS (from first found VM) ===")
        if first_vm and first_pve:
            print(f"Target VM: {first_vm['vmid']} on {first_pve.name}")
            try:
                # Test get_snapshots
                snaps = await proxmox_service.get_snapshots(
                    hostname=first_pve.hostname,
                    vmid=first_vm['vmid'],
                    vm_type=first_vm['type'],
                    port=first_pve.ssh_port,
                    username=first_pve.ssh_user,
                    key_path=first_pve.ssh_key_path
                )
                print(f"  -> get_snapshots returned {len(snaps)} items:")
                print(json.dumps(snaps, indent=2))
                
                # Test RAW pvesh command
                print("  -> Executing RAW pvesh command...")
                cmd = f"pvesh get /nodes/{first_pve.name}/qemu/{first_vm['vmid']}/snapshot --output-format json"
                if first_vm['type'] == 'lxc':
                     cmd = f"pvesh get /nodes/{first_pve.name}/lxc/{first_vm['vmid']}/snapshot --output-format json"
                
                res = await ssh_service.execute(first_pve.hostname, cmd, first_pve.ssh_port, first_pve.ssh_user, first_pve.ssh_key_path)
                print(f"  -> RAW Output:\n{res.stdout}")
                
            except Exception as e:
                print(f"  -> Error fetching snapshots: {e}")
        else:
            print("  -> No VM found to test snapshots.")

        print("\n=== 3. PBS BACKUPS INSPECTION ===")
        pbs_nodes = db.query(Node).filter(Node.node_type == 'pbs').all()
        for pbs in pbs_nodes:
            print(f"PBS Node: {pbs.name} ({pbs.hostname}) - Datastore: {pbs.pbs_datastore}")
            ds = pbs.pbs_datastore or "backup"
            
            try:
                # 1. Direct connection test
                print("  -> Testing direct SSH connection...")
                uname_res = await ssh_service.execute(pbs.hostname, "uname -a", pbs.ssh_port, pbs.ssh_user, pbs.ssh_key_path)
                print(f"     Result: {'OK' if uname_res.success else 'FAIL'} - {uname_res.stdout.strip()[:50]}...")
                
                # 1.5 Test Fingerprint Fetching
                print("  -> Testing Fingerprint Fetching (RAW)...")
                cert_cmd = "proxmox-backup-manager cert info --output-format json"
                cert_res = await ssh_service.execute(pbs.hostname, cert_cmd, pbs.ssh_port, pbs.ssh_user, pbs.ssh_key_path)
                print(f"     Cert Info Success: {cert_res.success}")
                print(f"     Cert Info STDOUT: {cert_res.stdout}")
                print(f"     Cert Info STDERR: {cert_res.stderr}")
                
                # 2. List ALL backups (raw)
                print(f"  -> Listing ALL backups on datastore '{ds}' (limit 10)...")
                # Note: We use list_backups but bypass the filtering in our script manually
                # Actually, let's call the raw command
                pbs_repo = f"{pbs.pbs_username}@{pbs.hostname}:{ds}"
                env_prefix = f"PBS_PASSWORD='{pbs.pbs_password}' " if pbs.pbs_password else ""
                cmd = f"{env_prefix}proxmox-backup-client snapshot list --repository {pbs_repo} --output-format json 2>/dev/null"
                
                # Run command from... WHERE? 
                # Ideally from the PVE node if possible, or from the machine running this script if it has client.
                # But typically we run `proxmox-backup-client` ON the PBS node itself (localhost repo) OR from a PVE node.
                # Let's try running IT ON THE PBS NODE ITSELF addressing 'localhost' or the path directly?
                # Usually `proxmox-backup-client` connects to a server. On the server itself, we can use `proxmox-backup-manager`.
                
                # Let's try using `proxmox-backup-debug` or similar on PBS node, OR running the client on the PVE node.
                # Since we know PVE nodes connect to PBS, let's use `first_pve` to query PBS if available.
                
                if first_pve:
                     print(f"  -> Executing client from PVE node {first_pve.name}...")
                     # We need to construct a valid command valid from PVE.
                     # But PVE adds storage via `pvesm`.
                     # Let's try `pvesm list <storage>` on PVE.
                     
                     # First list storages to find the PBS one
                     stor_res = await ssh_service.execute(first_pve.hostname, "pvesm status --content backup --output-format json", first_pve.ssh_port, first_pve.ssh_user, first_pve.ssh_key_path)
                     pbs_storage_id = None
                     if stor_res.success:
                         stors = json.loads(stor_res.stdout)
                         for s in stors:
                             if s['type'] == 'pbs':
                                 print(f"     Found PBS storage on PVE: {s['storage']}")
                                 pbs_storage_id = s['storage']
                                 break
                     
                     if pbs_storage_id:
                         cmd = f"pvesm list {pbs_storage_id} --output-format json"
                         res = await ssh_service.execute(first_pve.hostname, cmd, first_pve.ssh_port, first_pve.ssh_user, first_pve.ssh_key_path)
                         print(f"     pvesm list result: {len(res.stdout)} bytes")
                         try:
                             backups = json.loads(res.stdout)
                             print(f"     Found {len(backups)} backups total.")
                             for b in backups[:5]:
                                 print(f"     - {b}")
                         except:
                             print(f"     Raw output: {res.stdout}")
                     else:
                         print("     No PBS storage configured on this PVE node.")
                
                # Also try direct PBS query via our service (which uses client on the 'from' node or direct)
                # If we pass from_node_hostname=None, it tries to run `proxmox-backup-client` ON THE TARGET PBS HOST.
                # Does the target PBS host have the client installed? Yes, usually.
                # But it needs to connect to the service.
                
                print(f"  -> Attempting direct listing via pbs_service (running on PBS node)...")
                # Manually construct command to debug it
                pbs_repo = f"{pbs.pbs_username}@{pbs.hostname}:{ds}"
                env = f"PBS_PASSWORD='{pbs.pbs_password}' " if pbs.pbs_password else ""
                cmd = f"{env}proxmox-backup-client snapshot list --repository {pbs_repo} --output-format json"
                
                print(f"     CMD: {cmd.replace(pbs.pbs_password, '***') if pbs.pbs_password else cmd}")
                
                res = await ssh_service.execute(pbs.hostname, cmd, pbs.ssh_port, pbs.ssh_user, pbs.ssh_key_path)
                if res.success:
                    print(f"     RAW STDOUT: {res.stdout[:500]}...")
                    try:
                       backups = json.loads(res.stdout)
                       print(f"     Parsed {len(backups)} backups.")
                       for b in backups[:5]: print(f"     - {b}")
                    except:
                       print("     Failed to parse JSON")
                else:
                    print(f"     FAIL. Exit code: {res.exit_code}")
                    print(f"     STDERR: {res.stderr}")

            except Exception as e:
                print(f"  -> Error inspecting PBS: {e}")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(debug_inspection())
