"""
Migration: Add mining pool tracking to OP_RETURN scans
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from db_config import engine

def upgrade():
    """Add mined_by and coinbase_text columns to op_return_scans table"""
    with engine.connect() as connection:
        try:
            # Add mined_by column
            connection.execute(text("""
                ALTER TABLE op_return_scans 
                ADD COLUMN mined_by VARCHAR(100) AFTER large_op_returns_found
            """))
            print("[OK] Added mined_by column")
        except Exception as e:
            if "Duplicate column name" in str(e):
                print("[SKIP] mined_by column already exists")
            else:
                raise
        
        try:
            # Add coinbase_text column
            connection.execute(text("""
                ALTER TABLE op_return_scans 
                ADD COLUMN coinbase_text TEXT AFTER mined_by
            """))
            print("[OK] Added coinbase_text column")
        except Exception as e:
            if "Duplicate column name" in str(e):
                print("[SKIP] coinbase_text column already exists")
            else:
                raise
        
        try:
            # Add index on mined_by
            connection.execute(text("""
                CREATE INDEX idx_op_return_scans_mined_by ON op_return_scans(mined_by)
            """))
            print("[OK] Added index on mined_by")
        except Exception as e:
            if "Duplicate key name" in str(e):
                print("[SKIP] Index on mined_by already exists")
            else:
                raise
        
        connection.commit()
    
    print("\n[DONE] Migration complete!")

if __name__ == "__main__":
    upgrade()

