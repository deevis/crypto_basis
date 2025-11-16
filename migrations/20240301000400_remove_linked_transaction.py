import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine

def migrate():
    with engine.connect() as connection:
        try:
            # Drop the foreign key constraint first
            connection.execute(text("""
                ALTER TABLE transactions 
                DROP FOREIGN KEY transactions_ibfk_1
            """))
            
            # Then drop the column
            connection.execute(text("""
                ALTER TABLE transactions 
                DROP COLUMN linked_transaction_id
            """))
            
            print("Removed linked_transaction_id column")
            
        except Exception as e:
            print(f"Error removing column: {e}")

if __name__ == "__main__":
    migrate() 