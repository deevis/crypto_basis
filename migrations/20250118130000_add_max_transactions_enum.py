"""Add MAX_TRANSACTIONS to termination_reason enum"""

from sqlalchemy import text


def migrate():
    """Alter termination_reason enum to include MAX_TRANSACTIONS"""
    from db_config import engine
    
    with engine.connect() as connection:
        # MySQL requires recreating the enum - ALTER COLUMN with new enum definition
        connection.execute(text("""
            ALTER TABLE btc_utxo_trace_history 
            MODIFY COLUMN termination_reason 
            ENUM('PENDING', 'COINBASE', 'EXCHANGE', 'MAX_HOPS', 'MAX_TRANSACTIONS', 'ERROR') 
            DEFAULT 'PENDING'
        """))
        
        connection.commit()
        print("Added MAX_TRANSACTIONS to termination_reason enum")
