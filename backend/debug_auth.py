
import asyncio
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup path and DB
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database import Base, Node, SQLALCHEMY_DATABASE_URL, SystemConfig, get_config_value, User
from services.proxmox_auth_service import proxmox_auth_service

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

async def test_auth():
    db = SessionLocal()
    try:
        print("--- Testing Auth Logic ---")
        
        # 1. Check Config
        auth_method = get_config_value(db, "auth_method", "proxmox")
        print(f"Auth Method: {auth_method}")
        
        # 2. Check Auth Node
        node = db.query(Node).filter(Node.is_auth_node == True, Node.is_active == True).first()
        if not node:
             node = db.query(Node).filter(Node.is_online == True, Node.is_active == True).first()
        
        if node:
            print(f"Auth Node: {node.name} ({node.hostname})")
            
            # 3. Test Realms Fetch (common failure point)
            print(f"Fetching realms from {node.hostname}...")
            try:
                realms = await proxmox_auth_service.get_available_realms(
                    api_host=node.hostname,
                    port=8006,
                    verify_ssl=node.proxmox_verify_ssl
                )
                print(f"Realms: {realms}")
            except Exception as e:
                print(f"ERROR fetching realms: {e}")
                
            # 4. Test Authenticate
            print("Testing authentication for admin...")
            # Note: We need a valid password to really test, but let's see if it connects at least
            # We can't easily test valid auth without credentials, but we can check if it hangs or returns invalid creds instantly.
            try:
                success, user, error = await proxmox_auth_service.authenticate(
                    api_host=node.hostname,
                    username="admin",
                    password="wrongpassword", # Expect failure, not hang
                    realm="pam",
                    port=8006,
                    verify_ssl=node.proxmox_verify_ssl
                )
                print(f"Auth Result: Success={success}, Error={error}")
            except Exception as e:
                print(f"ERROR authenticating: {e}")

        else:
            print("NO AUTH NODE FOUND!")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_auth())
