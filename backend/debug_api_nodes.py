
import requests
import json

def check_nodes_api():
    try:
        # Correct URL
        response = requests.get('http://localhost:8420/api/nodes/')
        if response.status_code == 200:
            nodes = response.json()
            print(f"API Returned {len(nodes)} nodes.")
            for node in nodes:
                print(f"Node: {node.get('name')} | Type: {node.get('node_type')} | PBS Datastore: '{node.get('pbs_datastore')}'")
                if node.get('name') == 'DA-PBS':
                     print("FULL DA-PBS Payload:", json.dumps(node, indent=2))
        else:
            print(f"Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    check_nodes_api()
