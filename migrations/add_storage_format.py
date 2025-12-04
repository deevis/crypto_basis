"""
Migration: Add storage_format column to large_op_returns table
Run this after updating models.py to add storage_format column
"""
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

def migrate():
    """Add storage_format column to large_op_returns table"""
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'database': os.getenv('DB_NAME')
    }
    
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    
    try:
        print("Adding storage_format column to large_op_returns table...")
        
        # Check if column already exists
        cursor.execute("""
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = %s 
            AND TABLE_NAME = 'large_op_returns'
            AND COLUMN_NAME = 'storage_format'
        """, (db_config['database'],))
        
        if cursor.fetchone():
            print("  Column storage_format already exists, skipping")
        else:
            # Add column after is_text column
            sql = """
                ALTER TABLE large_op_returns 
                ADD COLUMN storage_format VARCHAR(50) NULL 
                COMMENT 'Storage format: base64, data_uri, raw, hex, gzip, etc.'
                AFTER is_text
            """
            print("  Adding column: storage_format")
            cursor.execute(sql)
            
            # Set default value for existing rows
            print("  Setting default value 'raw' for existing rows")
            cursor.execute("""
                UPDATE large_op_returns 
                SET storage_format = 'raw' 
                WHERE storage_format IS NULL
            """)
        
        conn.commit()
        print("Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    migrate()

