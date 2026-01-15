
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

# Setup path and DB
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database import Node, SQLALCHEMY_DATABASE_URL

def list_all_nodes():
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    nodes = db.query(Node).all()
    print(f"Total Nodes: {len(nodes)}")
    for n in nodes:
        print(f"ID: {n.id} | Name: {n.name} | Host: {n.hostname} | Type: {n.node_type} | Datastore: '{n.pbs_datastore}'")
    
    db.close()

if __name__ == "__main__":
    list_all_nodes()
