import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine

def migrate():
    with engine.connect() as connection:
        try:
            connection.execute(text("""
                CREATE TABLE wallet_transfers (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    out_transaction_id INTEGER NOT NULL,
                    in_transaction_id INTEGER NOT NULL,
                    amount FLOAT NOT NULL,
                    CONSTRAINT fk_out_tx FOREIGN KEY (out_transaction_id) REFERENCES transactions(id),
                    CONSTRAINT fk_in_tx FOREIGN KEY (in_transaction_id) REFERENCES transactions(id),
                    CONSTRAINT unique_out_transaction UNIQUE (out_transaction_id),
                    CONSTRAINT unique_in_transaction UNIQUE (in_transaction_id),
                    CONSTRAINT different_transactions CHECK (out_transaction_id != in_transaction_id)
                )
            """))
            print("Created wallet_transfers table")
            
        except Exception as e:
            print(f"Error creating table: {e}")

if __name__ == "__main__":
    migrate() 