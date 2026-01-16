
import os
import uvicorn
import sys

if __name__ == "__main__":
    # Setup environment for local development
    base_dir = os.path.expanduser("~/.dapx-unified")
    
    os.environ["DAPX_DATA_DIR"] = base_dir
    os.environ["DAPX_CONFIG_DIR"] = os.path.join(base_dir, "config")
    os.environ["DAPX_LOG_DIR"] = os.path.join(base_dir, "logs")
    os.environ["DAPX_Install_DIR"] = os.getcwd() # Mock install dir
    
    print(f"Setting up environment:")
    print(f"DATA_DIR: {os.environ['DAPX_DATA_DIR']}")
    print(f"CONFIG_DIR: {os.environ['DAPX_CONFIG_DIR']}")
    print(f"LOG_DIR: {os.environ['DAPX_LOG_DIR']}")
    
    # Ensure directories exist
    os.makedirs(os.environ["DAPX_DATA_DIR"], exist_ok=True)
    os.makedirs(os.environ["DAPX_CONFIG_DIR"], exist_ok=True)
    os.makedirs(os.environ["DAPX_LOG_DIR"], exist_ok=True)
    
    # Create backups dir explicitly
    os.makedirs(os.path.join(base_dir, "backups"), exist_ok=True)
    
    # Run server
    try:
        uvicorn.run("main:app", host="0.0.0.0", port=8420, reload=True)
    except KeyboardInterrupt:
        print("\nServer stopped")
