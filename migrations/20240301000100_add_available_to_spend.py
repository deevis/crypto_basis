import os
import sys

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine
from models import Transaction, OperationType
from db_config import SessionLocal

def migrate():
    # Add column if it doesn't exist
    with engine.connect() as connection:
        try:
            connection.execute(text("""
                ALTER TABLE transactions 
                ADD COLUMN available_to_spend FLOAT NULL
            """))
            print("Added available_to_spend column")
        except Exception as e:
            print(f"Column might already exist: {e}")
            
    # Backfill data
    session = SessionLocal()
    try:
        # Set available_to_spend for IN transactions
        session.execute(text("""
            UPDATE transactions 
            SET available_to_spend = operation_amount 
            WHERE operation_type = 'IN'
        """))
        
        # Set available_to_spend to NULL for OUT transactions
        session.execute(text("""
            UPDATE transactions 
            SET available_to_spend = NULL 
            WHERE operation_type = 'OUT'
        """))
        
        session.commit()
        print("Backfilled available_to_spend data")
        
    except Exception as e:
        session.rollback()
        print(f"Error backfilling data: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    migrate() 