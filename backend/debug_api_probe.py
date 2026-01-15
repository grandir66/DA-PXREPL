
import requests
import json
import sys

# ... (imports)

# Configuration
API_URL = "http://localhost:8420"
USERNAME = "admin"
PASSWORD = "admin" # assuming default from setup

def login():
    print("--- Logging in ---")
    # Correct endpoint is /api/auth/login and expects JSON body
    resp = requests.post(f"{API_URL}/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    if resp.status_code == 200:
        token = resp.json()['access_token']
        print("Login successful.")
        return token
    else:
        print(f"Login failed: {resp.status_code} {resp.text}")
        return None

def main():
    token = login()
    if not token: return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        # 1. Get Nodes
        print("--- Fetching Nodes ---")
        resp = requests.get(f"{API_URL}/api/nodes", headers=headers) # api/dashboard/nodes is different? checking routers.
        # routers/host_info.py -> /dashboard/nodes
        # routers/nodes.py -> /api/nodes 
        # API prefix is /api in main.py? 
        # main.py includes router host_info without prefix /api? Let's check main.py.
        # usually /api/dashboard/nodes based on previous interactions using /dashboard/vms
        
        # Let's try /api/dashboard/nodes first as per previous successful curls in other sessions?
        # Actually previous session used /dashboard/nodes in host_info.py but wait...
        # host_info router prefix is /dashboard. 
        # But main.py might include it with /api prefix?
        
        # Let's try both or just /api/dashboard/nodes if global prefix is /api.
        
        resp = requests.get(f"{API_URL}/api/dashboard/nodes", headers=headers)
        if resp.status_code != 200:
             # Try without /api
             resp = requests.get(f"{API_URL}/dashboard/nodes", headers=headers)
        
        if resp.status_code != 200:
            print(f"Failed to fetch nodes: {resp.status_code} {resp.text}")
            return

        nodes = resp.json()
        if not nodes:
            print("No nodes found.")
            return

        target_vm_name = "da-SNS-DEV"
        found_target = False

        for node in nodes:
            node_id = node['id']
            node_name = node['name']
            if not node.get('is_online'):
                continue
                
            print(f"\n--- Checking Node: {node_name} (ID: {node_id}) ---")
            
            # Fetch VMs
            resp = requests.get(f"{API_URL}/api/vms/node/{node_id}", headers=headers)
            if resp.status_code == 200:
                vms = resp.json()
                for vm in vms:
                    vmid = vm.get('vmid')
                    name = vm.get('name')
                    # print(f"  vm: {name} ({vmid})")
                    
                    if target_vm_name.lower() in name.lower() or name.lower() in target_vm_name.lower():
                        print(f"  >>> FOUND TARGET: {name} (ID: {vmid}) on Node {node_name}")
                        found_target = True
                        
                        # Fetch Full Details (Snapshots)
                        print(f"  --- Fetching Full Details for {name} ---")
                        url = f"{API_URL}/api/vms/node/{node_id}/vm/{vmid}/full-details"
                        resp_det = requests.get(url, headers=headers)
                        if resp_det.status_code == 200:
                            details = resp_det.json()
                            snaps = details.get('snapshots', [])
                            print(f"  Snapshots found: {len(snaps)}")
                            print(json.dumps(snaps, indent=2))
                        else:
                            print(f"  Failed to fetch details: {resp_det.status_code}")
                        
                        # break # Keep looking in case of duplicates? No, just stop for this node maybe.

        if not found_target:
            print(f"\nCould not find VM named '{target_vm_name}'")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
