import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine

def migrate():
    with engine.connect() as connection:
        try:
            # Create exchanges table
            connection.execute(text("""
                CREATE TABLE exchanges (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    name VARCHAR(50) NOT NULL UNIQUE,
                    description VARCHAR(200),
                    active BOOLEAN DEFAULT TRUE,
                    created_date DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("Created exchanges table")
            
            # Create exchange_transfers table
            connection.execute(text("""
                CREATE TABLE exchange_transfers (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    exchange_id INTEGER NOT NULL,
                    out_transaction_id INTEGER NOT NULL,
                    sale_price FLOAT,
                    sale_amount FLOAT,
                    sale_date DATETIME,
                    realized_gain FLOAT,
                    CONSTRAINT fk_exchange FOREIGN KEY (exchange_id) REFERENCES exchanges(id),
                    CONSTRAINT fk_out_tx_exchange FOREIGN KEY (out_transaction_id) REFERENCES transactions(id),
                    CONSTRAINT unique_exchange_transfer UNIQUE (out_transaction_id),
                    CONSTRAINT check_sale_amount CHECK (sale_amount >= 0)
                )
            """))
            print("Created exchange_transfers table")
            
        except Exception as e:
            print(f"Error creating tables: {e}")

if __name__ == "__main__":
    migrate() 