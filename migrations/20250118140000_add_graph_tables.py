"""Add graph-ready tables for UTXO tracing visualization"""

from sqlalchemy import text


def migrate():
    """Create tables for storing transaction graph data"""
    from db_config import engine
    
    with engine.connect() as connection:
        # Create btc_traced_transactions table
        connection.execute(text("""
            CREATE TABLE btc_traced_transactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                txid VARCHAR(64) NOT NULL UNIQUE,
                block_height INT,
                block_time TIMESTAMP NULL,
                input_count INT,
                output_count INT,
                is_coinbase BOOLEAN DEFAULT FALSE,
                is_exchange_like BOOLEAN DEFAULT FALSE,
                boundary_type ENUM('NONE', 'COINBASE', 'EXCHANGE') DEFAULT 'NONE',
                exchange_indicators TEXT,
                first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                
                INDEX idx_traced_tx_txid (txid),
                INDEX idx_traced_tx_boundary (boundary_type),
                INDEX idx_traced_tx_block (block_height)
            )
        """))
        print("Created btc_traced_transactions table")
        
        # Create btc_traced_addresses table
        # Note: monitoring_id must be BIGINT UNSIGNED to match btc_address_monitoring.id (SERIAL)
        connection.execute(text("""
            CREATE TABLE btc_traced_addresses (
                id INT AUTO_INCREMENT PRIMARY KEY,
                address VARCHAR(100) NOT NULL UNIQUE,
                is_monitored BOOLEAN DEFAULT FALSE,
                monitoring_id BIGINT UNSIGNED,
                is_exchange_address BOOLEAN DEFAULT FALSE,
                first_seen_block INT,
                last_seen_block INT,
                total_received DECIMAL(18,8) DEFAULT 0,
                total_sent DECIMAL(18,8) DEFAULT 0,
                first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                
                CONSTRAINT fk_traced_addr_monitoring 
                    FOREIGN KEY (monitoring_id) REFERENCES btc_address_monitoring(id) ON DELETE SET NULL,
                    
                INDEX idx_traced_addr_address (address),
                INDEX idx_traced_addr_monitored (is_monitored)
            )
        """))
        print("Created btc_traced_addresses table")
        
        # Create btc_transaction_flows table
        connection.execute(text("""
            CREATE TABLE btc_transaction_flows (
                id INT AUTO_INCREMENT PRIMARY KEY,
                from_txid_id INT NOT NULL,
                from_vout INT NOT NULL,
                to_txid_id INT NOT NULL,
                to_vin INT NOT NULL,
                amount DECIMAL(18,8) NOT NULL,
                from_address_id INT,
                to_address_id INT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                
                CONSTRAINT fk_flow_from_tx 
                    FOREIGN KEY (from_txid_id) REFERENCES btc_traced_transactions(id) ON DELETE CASCADE,
                CONSTRAINT fk_flow_to_tx 
                    FOREIGN KEY (to_txid_id) REFERENCES btc_traced_transactions(id) ON DELETE CASCADE,
                CONSTRAINT fk_flow_from_addr 
                    FOREIGN KEY (from_address_id) REFERENCES btc_traced_addresses(id) ON DELETE SET NULL,
                CONSTRAINT fk_flow_to_addr 
                    FOREIGN KEY (to_address_id) REFERENCES btc_traced_addresses(id) ON DELETE SET NULL,
                    
                CONSTRAINT unique_flow UNIQUE (from_txid_id, from_vout, to_txid_id, to_vin),
                
                INDEX idx_flow_from_tx (from_txid_id),
                INDEX idx_flow_to_tx (to_txid_id),
                INDEX idx_flow_from_addr (from_address_id),
                INDEX idx_flow_to_addr (to_address_id)
            )
        """))
        print("Created btc_transaction_flows table")
        
        connection.commit()
        print("All graph tables created successfully")
