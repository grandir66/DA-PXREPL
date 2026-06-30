
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# Setup path and DB
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database import Node, SQLALCHEMY_DATABASE_URL

def get_params():
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # Get a working PVE node
    pve = db.query(Node).filter(Node.name == 'DA-PX-05').first()
    if pve:
        print(f"Working Node Key Path: {pve.ssh_key_path}")
        print(f"Working Node User: {pve.ssh_user}")
        
    # Get PBS node
    pbs = db.query(Node).filter(Node.name == 'DA-PBS').first()
    if pbs:
        print(f"PBS Node Key Path: {pbs.ssh_key_path}")
    
    db.close()

if __name__ == "__main__":
    get_params()
