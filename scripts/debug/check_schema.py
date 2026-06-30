
from sqlalchemy import create_engine, inspect
import sys
import os

# Setup path and DB
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database import SQLALCHEMY_DATABASE_URL

def check_schema():
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    inspector = inspect(engine)
    columns = inspector.get_columns('nodes')
    
    found = False
    print("--- Nodes Table Columns ---")
    for col in columns:
        print(f"{col['name']} ({col['type']})")
        if col['name'] == 'pbs_datastore':
            found = True
            
    if found:
        print("\nSUCCESS: 'pbs_datastore' column exists.")
    else:
        print("\nFAILURE: 'pbs_datastore' column MISSING!")

if __name__ == "__main__":
    check_schema()
