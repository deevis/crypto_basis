import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine

def migrate():
    with engine.connect() as connection:
        try:
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS migrations (
                    id INTEGER PRIMARY KEY AUTO_INCREMENT,
                    migration_name VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("Created migrations table")
            
        except Exception as e:
            print(f"Error creating migrations table: {e}")

if __name__ == "__main__":
    migrate() 