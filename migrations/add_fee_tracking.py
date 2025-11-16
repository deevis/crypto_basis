"""
Migration: Add fee tracking columns to large_op_returns table
Run this after updating models.py to add fee-related columns
"""
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

def migrate():
    """Add fee tracking columns to large_op_returns table"""
    db_config = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'database': os.getenv('DB_NAME')
    }
    
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    
    try:
        print("Adding fee tracking columns to large_op_returns table...")
        
        # Check if columns already exist
        cursor.execute("""
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = %s 
            AND TABLE_NAME = 'large_op_returns'
            AND COLUMN_NAME IN ('tx_fee', 'tx_size', 'fee_rate', 'cost_per_byte', 'tx_input_count', 'tx_output_count')
        """, (db_config['database'],))
        
        existing_columns = {row[0] for row in cursor.fetchall()}
        
        # Add columns if they don't exist
        columns_to_add = [
            ("tx_fee", "INT NULL COMMENT 'Total transaction fee in satoshis'"),
            ("tx_size", "INT NULL COMMENT 'Transaction size in vbytes'"),
            ("fee_rate", "FLOAT NULL COMMENT 'Fee rate in sats/vbyte'"),
            ("cost_per_byte", "FLOAT NULL COMMENT 'Cost per byte of OP_RETURN data'"),
            ("tx_input_count", "INT NULL COMMENT 'Number of transaction inputs'"),
            ("tx_output_count", "INT NULL COMMENT 'Number of transaction outputs'"),
        ]
        
        for col_name, col_def in columns_to_add:
            if col_name not in existing_columns:
                sql = f"ALTER TABLE large_op_returns ADD COLUMN {col_name} {col_def}"
                print(f"  Adding column: {col_name}")
                cursor.execute(sql)
            else:
                print(f"  Column {col_name} already exists, skipping")
        
        # Add index on fee_rate if it doesn't exist
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.STATISTICS 
            WHERE TABLE_SCHEMA = %s 
            AND TABLE_NAME = 'large_op_returns'
            AND INDEX_NAME = 'idx_large_op_returns_fee_rate'
        """, (db_config['database'],))
        
        if cursor.fetchone()[0] == 0:
            print("  Adding index on fee_rate")
            cursor.execute("""
                CREATE INDEX idx_large_op_returns_fee_rate 
                ON large_op_returns(fee_rate)
            """)
        else:
            print("  Index on fee_rate already exists")
        
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

