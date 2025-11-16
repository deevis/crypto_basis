from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, UniqueConstraint, CheckConstraint, Boolean, func, Numeric, Index, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum
from datetime import timedelta, datetime

Base = declarative_base()

class OperationType(enum.Enum):
    IN = "IN"
    OUT = "OUT"
    NFT_IN = "NFT_IN"  # These will be ignored - shown as disabled in the UI

class TransactionFulfillment(Base):
    __tablename__ = 'transaction_fulfillments'
    
    id = Column(Integer, primary_key=True)
    out_transaction_id = Column(Integer, ForeignKey('transactions.id'), nullable=False)
    in_transaction_id = Column(Integer, ForeignKey('transactions.id'), nullable=False)
    in_transaction_amount = Column(Float, nullable=False)
    in_transaction_cost_basis = Column(Float, nullable=False)
    out_transaction_percent_filled = Column(Float, nullable=False)
    
    # Relationships
    out_transaction = relationship("Transaction", foreign_keys=[out_transaction_id], back_populates="fulfillments")
    in_transaction = relationship("Transaction", foreign_keys=[in_transaction_id])
    
    # Constraints
    __table_args__ = (
        # Ensure percent filled is between 0 and 100
        CheckConstraint('out_transaction_percent_filled >= 0 AND out_transaction_percent_filled <= 100', 
                       name='check_percent_filled_range'),
        # Ensure unique combination of out_transaction_id and in_transaction_id
        UniqueConstraint('out_transaction_id', 'in_transaction_id', 
                        name='unique_fulfillment_combination'),
    )

class Transaction(Base):
    __tablename__ = 'transactions'
    
    id = Column(Integer, primary_key=True)
    wallet_name = Column(String(50), nullable=False)
    countervalue_ticker = Column(String(10), nullable=False)
    currency_ticker = Column(String(10), nullable=False)
    operation_type = Column(Enum(OperationType), nullable=False)
    operation_date = Column(DateTime, nullable=False)
    operation_amount = Column(Float, nullable=False)
    operation_fees = Column(Float, nullable=False)
    cost_basis_minus_fees = Column(Float, nullable=False)
    cost_basis = Column(Float, nullable=False)
    status = Column(String(20), nullable=False)
    account_name = Column(String(50), nullable=False)
    account_xpub = Column(String(200), nullable=False)
    countervalue_at_operation = Column(Float, nullable=False)
    operation_hash = Column(String(200), nullable=False)
    available_to_spend = Column(Float, nullable=True)
    memo = Column(String(200))
    
    # Add new column for block number
    block_number = Column(Integer, nullable=True)  # Nullable since not all transactions will have this
    block_time = Column(DateTime, nullable=True)   # Add block timestamp too
    
    # Link to associated IN transaction for OUT transactions
    # linked_transaction_id = Column(Integer, ForeignKey('transactions.id'), nullable=True)
    # linked_transaction = relationship("Transaction", remote_side=[id])
    
    # Link to fulfillments
    fulfillments = relationship("TransactionFulfillment", 
                              foreign_keys=[TransactionFulfillment.out_transaction_id],
                              back_populates="out_transaction")

    # Create composite unique constraint
    __table_args__ = (
        UniqueConstraint('operation_hash', 'operation_type', 'wallet_name', 
                        name='unique_operation_per_wallet'),
    ) 

class WalletTransfer(Base):
    __tablename__ = 'wallet_transfers'
    
    id = Column(Integer, primary_key=True)
    out_transaction_id = Column(Integer, ForeignKey('transactions.id'), nullable=False)
    in_transaction_id = Column(Integer, ForeignKey('transactions.id'), nullable=False)
    amount = Column(Float, nullable=False)
    
    # Relationships
    out_transaction = relationship("Transaction", foreign_keys=[out_transaction_id], backref="outgoing_transfer")
    in_transaction = relationship("Transaction", foreign_keys=[in_transaction_id], backref="incoming_transfer")
    
    # Constraints
    __table_args__ = (
        # Ensure unique OUT and IN transactions
        UniqueConstraint('out_transaction_id', name='unique_out_transaction'),
        UniqueConstraint('in_transaction_id', name='unique_in_transaction'),
        # Ensure OUT and IN transactions are different
        CheckConstraint('out_transaction_id != in_transaction_id', name='different_transactions'),
    ) 

class Exchange(Base):
    __tablename__ = 'exchanges'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    description = Column(String(200))
    active = Column(Boolean, default=True)
    created_date = Column(DateTime, default=func.now())

class CapitalGainsTerm(enum.Enum):
    SHORT = "SHORT"
    LONG = "LONG"

class ExchangeTransfer(Base):
    __tablename__ = 'exchange_transfers'
    
    id = Column(Integer, primary_key=True)
    exchange_id = Column(Integer, ForeignKey('exchanges.id'), nullable=False)
    out_transaction_id = Column(Integer, ForeignKey('transactions.id'), nullable=False)
    sale_price = Column(Float)
    sale_amount = Column(Float)
    sale_date = Column(DateTime)
    realized_gain = Column(Float)
    term_type = Column(Enum(CapitalGainsTerm))
    acquisition_price = Column(Float)  # Average cost basis of fulfilled amounts
    acquisition_date = Column(DateTime)  # Latest date from fulfillments
    fee = Column(Float, default=0.0)  # Add fee column
    
    # Relationships
    exchange = relationship("Exchange")
    out_transaction = relationship("Transaction", backref="exchange_transfer")
    
    def calculate_term_type(self, session):
        """Calculate whether this is a long or short term gain based on earliest fulfillment"""
        if not self.sale_date:
            return None
            
        # Get earliest IN transaction date from fulfillments
        earliest_date = session.query(func.min(Transaction.operation_date))\
            .join(TransactionFulfillment, 
                  TransactionFulfillment.in_transaction_id == Transaction.id)\
            .filter(TransactionFulfillment.out_transaction_id == self.out_transaction_id)\
            .scalar()
            
        if not earliest_date:
            return None
            
        holding_period = self.sale_date - earliest_date
        return CapitalGainsTerm.LONG if holding_period >= timedelta(days=365) else CapitalGainsTerm.SHORT
    
    def calculate_acquisition_details(self, session):
        """Calculate acquisition price and date from fulfillments"""
        if not self.sale_amount:
            return None, None
            
        # Get fulfillment details
        fulfillment_details = session.query(
            func.sum(TransactionFulfillment.in_transaction_amount).label('total_amount'),
            func.sum(TransactionFulfillment.in_transaction_amount * 
                    Transaction.cost_basis).label('total_cost'),
            func.max(Transaction.operation_date).label('latest_date')
        ).join(
            Transaction,
            TransactionFulfillment.in_transaction_id == Transaction.id
        ).filter(
            TransactionFulfillment.out_transaction_id == self.out_transaction_id
        ).first()
        
        if not fulfillment_details or not fulfillment_details.total_amount:
            return None, None
            
        # Calculate average acquisition price
        acquisition_price = fulfillment_details.total_cost / fulfillment_details.total_amount
        
        return acquisition_price, fulfillment_details.latest_date
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('out_transaction_id', name='unique_exchange_transfer'),
        CheckConstraint('sale_amount <= out_transaction.operation_amount', 
                       name='check_sale_amount_within_transfer'),
    ) 

class CoinPrice(Base):
    __tablename__ = 'coin_prices'
    
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), nullable=False)
    price_date = Column(DateTime, nullable=False)
    price_usd = Column(Float, nullable=False)
    source = Column(String(20), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        UniqueConstraint('ticker', 'price_date', name='uix_ticker_date'),
    ) 

class BTCAddressMonitoring(Base):
    __tablename__ = 'btc_address_monitoring'
    
    id = Column(Integer, primary_key=True)
    source_label = Column(String(100), nullable=False)
    bitcoin_address = Column(String(100), nullable=False, unique=True)
    last_check_timestamp = Column(DateTime)
    last_known_balance = Column(Numeric(18,8))
    last_block_checked = Column(Integer)
    last_transaction_hash = Column(String(64))
    last_activity_block = Column(Integer)  # New field for the most recent block with activity
    monitor_status = Column(String(20), nullable=False, default='active')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    notification_threshold = Column(Numeric(18,8))
    address_type = Column(String(20))
    origin_block_number = Column(Integer)
    
    # Relationships
    utxos = relationship("BTCAddressUTXO", back_populates="monitoring_entry")
    
    # Add constraint validations
    __table_args__ = (
        CheckConstraint(
            monitor_status.in_(['active', 'paused', 'disabled']),
            name='valid_monitor_status'
        ),
        CheckConstraint(
            address_type.in_(['p2pkh', 'p2sh', 'p2wpkh', 'p2wsh', 'p2tr', 'unknown']),
            name='valid_address_type'
        ),
    )

class BTCAddressUTXO(Base):
    __tablename__ = 'btc_address_utxos'
    
    id = Column(Integer, primary_key=True)
    bitcoin_address = Column(String(100), ForeignKey('btc_address_monitoring.bitcoin_address', ondelete='CASCADE'), nullable=False)
    txid = Column(String(64), nullable=False)
    vout = Column(Integer, nullable=False)
    amount = Column(Numeric(18,8), nullable=False)
    script_type = Column(String(20), nullable=False)
    spent_in_tx = Column(String(64))
    block_height = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    monitoring_entry = relationship("BTCAddressMonitoring", back_populates="utxos")
    
    # Add constraints and indexes
    __table_args__ = (
        UniqueConstraint('txid', 'vout', name='unique_utxo'),
        CheckConstraint(
            script_type.in_(['p2pkh', 'p2sh', 'p2wpkh', 'p2wsh', 'p2tr', 'unknown']),
            name='valid_script_type'
        ),
        Index('idx_btc_utxos_address', 'bitcoin_address'),
        Index('idx_btc_utxos_spent', 'spent_in_tx'),
    )

class OPReturnScan(Base):
    __tablename__ = 'op_return_scans'
    
    id = Column(Integer, primary_key=True)
    block_number = Column(Integer, nullable=False, unique=True)
    block_hash = Column(String(64), nullable=False)
    block_time = Column(DateTime, nullable=False)
    total_transactions = Column(Integer, nullable=False, default=0)
    large_op_returns_found = Column(Integer, nullable=False, default=0)
    mined_by = Column(String(100))  # Mining pool or miner name
    coinbase_text = Column(Text)  # Raw coinbase text for reference
    scanned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    op_returns = relationship("LargeOPReturn", back_populates="scan")
    
    # Add indexes for efficient queries
    __table_args__ = (
        Index('idx_op_return_scans_block_number', 'block_number'),
        Index('idx_op_return_scans_scanned_at', 'scanned_at'),
        Index('idx_op_return_scans_mined_by', 'mined_by'),
    )

class LargeOPReturn(Base):
    __tablename__ = 'large_op_returns'
    
    id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, ForeignKey('op_return_scans.id', ondelete='CASCADE'), nullable=False)
    block_number = Column(Integer, nullable=False)
    txid = Column(String(64), nullable=False)
    vout_index = Column(Integer, nullable=False)
    data_size = Column(Integer, nullable=False)
    raw_data = Column(Text, nullable=True)  # Hex encoded - NULL for very large files (stored on disk only)
    decoded_text = Column(Text)  # If it's text - using Text for large data
    file_type = Column(String(20))  # jpg, pdf, text, binary, etc.
    mime_type = Column(String(100))
    is_text = Column(Boolean, default=False)
    
    # Transaction fee information
    tx_fee = Column(Integer)  # Total transaction fee in satoshis
    tx_size = Column(Integer)  # Transaction size in vbytes
    fee_rate = Column(Float)  # Fee rate in sats/vbyte
    cost_per_byte = Column(Float)  # Cost per byte of OP_RETURN data (tx_fee / data_size)
    tx_input_count = Column(Integer)  # Number of inputs
    tx_output_count = Column(Integer)  # Number of outputs
    
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    scan = relationship("OPReturnScan", back_populates="op_returns")
    
    # Add constraints and indexes
    __table_args__ = (
        UniqueConstraint('txid', 'vout_index', name='unique_op_return_tx'),
        Index('idx_large_op_returns_block', 'block_number'),
        Index('idx_large_op_returns_txid', 'txid'),
        Index('idx_large_op_returns_file_type', 'file_type'),
        Index('idx_large_op_returns_fee_rate', 'fee_rate'),
        CheckConstraint('data_size > 83', name='check_op_return_size'),
    ) 