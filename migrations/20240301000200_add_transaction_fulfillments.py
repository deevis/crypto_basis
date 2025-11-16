import os
import sys

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine
from models import Base, TransactionFulfillment

def migrate():
    # Create the transaction_fulfillments table
    with engine.connect() as connection:
        try:
            connection.execute(text("""
                CREATE TABLE transaction_fulfillments (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    out_transaction_id INTEGER NOT NULL,
                    in_transaction_id INTEGER NOT NULL,
                    in_transaction_amount FLOAT NOT NULL,
                    in_transaction_cost_basis FLOAT NOT NULL,
                    out_transaction_percent_filled FLOAT NOT NULL,
                    CONSTRAINT fk_out_transaction 
                        FOREIGN KEY (out_transaction_id) 
                        REFERENCES transactions(id),
                    CONSTRAINT fk_in_transaction 
                        FOREIGN KEY (in_transaction_id) 
                        REFERENCES transactions(id),
                    CONSTRAINT check_percent_filled_range 
                        CHECK (out_transaction_percent_filled >= 0 
                              AND out_transaction_percent_filled <= 100),
                    CONSTRAINT unique_fulfillment_combination 
                        UNIQUE (out_transaction_id, in_transaction_id)
                )
            """))
            print("Created transaction_fulfillments table")
            
        except Exception as e:
            print(f"Error creating table: {e}")
            
        try:
            # Add indexes for better query performance
            connection.execute(text("""
                CREATE INDEX idx_out_transaction 
                ON transaction_fulfillments(out_transaction_id)
            """))
            connection.execute(text("""
                CREATE INDEX idx_in_transaction 
                ON transaction_fulfillments(in_transaction_id)
            """))
            print("Added indexes to transaction_fulfillments table")
            
        except Exception as e:
            print(f"Error creating indexes: {e}")

if __name__ == "__main__":
    migrate() 