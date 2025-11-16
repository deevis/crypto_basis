"""
Migration: Make raw_data column nullable for large OP_RETURNs
This allows us to store metadata in DB while keeping large files on disk only
"""
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

def migrate():
    """Make raw_data column nullable in large_op_returns table"""
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'database': os.getenv('DB_NAME')
    }
    
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    
    try:
        print("Making raw_data column nullable in large_op_returns table...")
        
        # Modify the column to allow NULL
        cursor.execute("""
            ALTER TABLE large_op_returns 
            MODIFY COLUMN raw_data TEXT NULL 
            COMMENT 'Hex encoded OP_RETURN data - NULL for very large files (stored on disk only)'
        """)
        
        conn.commit()
        print("Migration completed successfully!")
        print("raw_data column is now nullable - large files can be stored on disk only")
        
    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    migrate()


