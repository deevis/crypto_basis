import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine

def migrate():
    with engine.connect() as connection:
        try:
            connection.execute(text("""
                ALTER TABLE transactions 
                ADD COLUMN memo VARCHAR(200)
            """))
            print("Added memo column to transactions table")
            
        except Exception as e:
            print(f"Error adding column: {e}")

if __name__ == "__main__":
    migrate() 