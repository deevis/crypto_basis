"""Add Bitcoin address monitoring and UTXO tracking tables"""

from sqlalchemy import text

def migrate():
    """Create BTC monitoring and UTXO tables"""
    from db_config import engine
    
    with engine.connect() as connection:
        # Create btc_address_monitoring table
        connection.execute(text("""
            CREATE TABLE btc_address_monitoring (
                id SERIAL PRIMARY KEY,
                source_label VARCHAR(100) NOT NULL,
                bitcoin_address VARCHAR(100) NOT NULL UNIQUE,
                last_check_timestamp TIMESTAMP,
                last_known_balance DECIMAL(18,8),
                last_block_checked INTEGER,
                last_transaction_hash VARCHAR(64),
                monitor_status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notification_threshold DECIMAL(18,8),
                address_type VARCHAR(20),
                
                -- Add constraints
                CONSTRAINT valid_monitor_status CHECK (monitor_status IN ('active', 'paused', 'disabled')),
                CONSTRAINT valid_address_type CHECK (address_type IN ('p2pkh', 'p2sh', 'p2wpkh', 'p2wsh', 'p2tr', 'unknown'))
            )
        """))
        
        # Create btc_address_utxos table
        connection.execute(text("""
            CREATE TABLE btc_address_utxos (
                id SERIAL PRIMARY KEY,
                bitcoin_address VARCHAR(100) NOT NULL,
                txid VARCHAR(64) NOT NULL,
                vout INTEGER NOT NULL,
                amount DECIMAL(18,8) NOT NULL,
                script_type VARCHAR(20) NOT NULL,
                spent_in_tx VARCHAR(64),
                block_height INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                
                -- Add constraints
                FOREIGN KEY (bitcoin_address) REFERENCES btc_address_monitoring(bitcoin_address) ON DELETE CASCADE,
                CONSTRAINT unique_utxo UNIQUE (txid, vout),
                CONSTRAINT valid_script_type CHECK (script_type IN ('p2pkh', 'p2sh', 'p2wpkh', 'p2wsh', 'p2tr', 'unknown'))
            )
        """))
        
        # Create index on bitcoin_address for faster lookups
        connection.execute(text("""
            CREATE INDEX idx_btc_utxos_address ON btc_address_utxos(bitcoin_address)
        """))
        
        # Create index on spent_in_tx for faster spent status queries
        connection.execute(text("""
            CREATE INDEX idx_btc_utxos_spent ON btc_address_utxos(spent_in_tx)
        """))
        
        connection.commit() 