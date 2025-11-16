"""Add origin block number to BTC address monitoring"""

from sqlalchemy import text

def migrate():
    """Add origin_block_number column"""
    from db_config import engine
    
    with engine.connect() as connection:
        connection.execute(text("""
            ALTER TABLE btc_address_monitoring 
            ADD COLUMN origin_block_number INTEGER
        """))
        connection.commit() 