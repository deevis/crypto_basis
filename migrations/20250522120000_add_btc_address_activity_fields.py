from sqlalchemy import text
from db_config import engine

def migrate():
    """
    Add last_activity_block to BTCAddressMonitoring and ensure last_transaction_hash exists
    """
    with engine.connect() as connection:
        
        print("Adding last_activity_block column")
        connection.execute(text(
            "ALTER TABLE btc_address_monitoring ADD COLUMN last_activity_block INTEGER"
        ))
        
        connection.commit()
        print("Migration completed successfully") 