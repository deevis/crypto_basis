"""Fix block info columns to remove default values and clear incorrect data"""

from sqlalchemy import text

def migrate():
    """Remove defaults and clear incorrect block data"""
    from db_config import engine
    
    with engine.connect() as connection:
        # First clear any incorrect data
        connection.execute(text('UPDATE transactions SET block_time = NULL, block_number = NULL'))
        
        # Alter columns to ensure no default values
        connection.execute(text('ALTER TABLE transactions ALTER COLUMN block_time DROP DEFAULT'))
        connection.execute(text('ALTER TABLE transactions ALTER COLUMN block_number DROP DEFAULT'))
        
        connection.commit() 