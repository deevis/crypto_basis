"""Add UTXO trace history table for tracking UTXO provenance"""

from sqlalchemy import text


def migrate():
    """Create btc_utxo_trace_history table for storing UTXO backtracing results"""
    from db_config import engine
    
    with engine.connect() as connection:
        # Create btc_utxo_trace_history table
        # Note: root_utxo_id must be BIGINT UNSIGNED to match btc_address_utxos.id (SERIAL = BIGINT UNSIGNED)
        connection.execute(text("""
            CREATE TABLE btc_utxo_trace_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                root_utxo_id BIGINT UNSIGNED NOT NULL,
                hop_number INT NOT NULL,
                txid VARCHAR(64) NOT NULL,
                vout INT NOT NULL,
                amount DECIMAL(18,8) NOT NULL,
                block_height INT,
                block_time TIMESTAMP NULL,
                source_address VARCHAR(100),
                input_count INT,
                output_count INT,
                is_coinbase BOOLEAN DEFAULT FALSE,
                is_exchange_like BOOLEAN DEFAULT FALSE,
                exchange_indicators TEXT,
                termination_reason ENUM('PENDING', 'COINBASE', 'EXCHANGE', 'MAX_HOPS', 'ERROR') DEFAULT 'PENDING',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                
                -- Foreign key constraint
                CONSTRAINT fk_trace_root_utxo FOREIGN KEY (root_utxo_id) 
                    REFERENCES btc_address_utxos(id) ON DELETE CASCADE,
                
                -- Unique constraint for one entry per hop per root UTXO per txid:vout
                CONSTRAINT unique_trace_hop UNIQUE (root_utxo_id, hop_number, txid, vout)
            )
        """))
        
        # Create indexes for efficient queries
        connection.execute(text("""
            CREATE INDEX idx_trace_root_utxo ON btc_utxo_trace_history(root_utxo_id)
        """))
        
        connection.execute(text("""
            CREATE INDEX idx_trace_txid ON btc_utxo_trace_history(txid)
        """))
        
        connection.execute(text("""
            CREATE INDEX idx_trace_termination ON btc_utxo_trace_history(termination_reason)
        """))
        
        connection.commit()
        print("Created btc_utxo_trace_history table with indexes")
