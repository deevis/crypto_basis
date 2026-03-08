from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel, QPushButton, QHBoxLayout
from btc_service import BTCService
from db_config import SessionLocal
from models import BTCAddressMonitoring, BTCAddressUTXO
from decimal import Decimal
from sqlalchemy import func
import logging

logger = logging.getLogger(__name__)


class BTCUTXODialog(QDialog):
    def __init__(self, address, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"UTXOs for {address}")
        self.resize(700, 400)
        self.address = address
        self.btc_service = BTCService(test_connection=True)
        self.setup_ui()
        self.load_utxos()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.info_label = QLabel(f"UTXOs for address: {self.address}")
        layout.addWidget(self.info_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["TXID", "VOUT", "Amount (BTC)", "Block Height", "DB Status"])
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def load_utxos(self):
        """Load UTXOs from Bitcoin Core and sync to database"""
        utxos, total = self.btc_service.check_address_utxos(self.address)
        
        # Sync UTXOs to database
        synced_count, new_count, spent_count = self.sync_utxos_to_db(utxos)
        
        self.table.setRowCount(len(utxos))
        for i, utxo in enumerate(utxos):
            self.table.setItem(i, 0, QTableWidgetItem(utxo.get('txid', '')))
            self.table.setItem(i, 1, QTableWidgetItem(str(utxo.get('vout', ''))))
            self.table.setItem(i, 2, QTableWidgetItem(str(utxo.get('amount', ''))))
            # Try to get block height if available
            block_height = ''
            if 'height' in utxo:
                block_height = str(utxo['height'])
            self.table.setItem(i, 3, QTableWidgetItem(block_height))
            # Show if this UTXO was synced
            self.table.setItem(i, 4, QTableWidgetItem("✓ Synced"))
        
        status_text = f"UTXOs for address: {self.address} | Total: {total} BTC"
        if new_count > 0 or spent_count > 0:
            status_text += f" | Synced: {new_count} new, {spent_count} marked spent"
        self.info_label.setText(status_text)
    
    def sync_utxos_to_db(self, blockchain_utxos):
        """
        Sync UTXOs from blockchain to database.
        - Adds new UTXOs found on blockchain
        - Marks UTXOs as spent if no longer in blockchain unspent set
        
        Returns: (total_synced, new_count, spent_count)
        """
        db = SessionLocal()
        try:
            # Check if this address is being monitored
            monitoring = db.query(BTCAddressMonitoring).filter(
                BTCAddressMonitoring.bitcoin_address == self.address
            ).first()
            
            if not monitoring:
                logger.debug(f"Address {self.address} not in monitoring table, skipping sync")
                return 0, 0, 0
            
            # Build set of current blockchain UTXOs
            blockchain_utxo_keys = {f"{u['txid']}:{u['vout']}" for u in blockchain_utxos}
            
            # Get existing DB UTXOs for this address
            db_utxos = db.query(BTCAddressUTXO).filter(
                BTCAddressUTXO.bitcoin_address == self.address
            ).all()
            
            db_utxo_map = {f"{u.txid}:{u.vout}": u for u in db_utxos}
            
            new_count = 0
            spent_count = 0
            
            # Add new UTXOs from blockchain
            for utxo in blockchain_utxos:
                utxo_key = f"{utxo['txid']}:{utxo['vout']}"
                
                if utxo_key not in db_utxo_map:
                    # New UTXO - add to database
                    # Determine script type from address format
                    script_type = 'unknown'
                    if self.address.startswith('1'):
                        script_type = 'p2pkh'
                    elif self.address.startswith('3'):
                        script_type = 'p2sh'
                    elif self.address.startswith('bc1q'):
                        script_type = 'p2wpkh'
                    elif self.address.startswith('bc1p'):
                        script_type = 'p2tr'
                    elif self.address.startswith('bc1') and len(self.address) > 42:
                        script_type = 'p2wsh'
                    
                    # Get block height
                    block_height = utxo.get('height', 0)
                    if not block_height and self.btc_service.is_available:
                        try:
                            tx_info = self.btc_service.get_raw_transaction_info(utxo['txid'])
                            block_height = tx_info.get('block_number', 0)
                        except Exception as e:
                            logger.warning(f"Could not get block height for {utxo['txid']}: {e}")
                            block_height = 0
                    
                    new_utxo = BTCAddressUTXO(
                        bitcoin_address=self.address,
                        txid=utxo['txid'],
                        vout=utxo['vout'],
                        amount=Decimal(str(utxo.get('amount', 0))),
                        script_type=script_type,
                        block_height=block_height or 0,
                        spent_in_tx=None
                    )
                    db.add(new_utxo)
                    new_count += 1
                    logger.info(f"Added new UTXO to DB: {utxo_key}")
                
                else:
                    # UTXO exists - make sure it's not marked as spent
                    existing = db_utxo_map[utxo_key]
                    if existing.spent_in_tx is not None:
                        # Was marked spent but is actually unspent - clear the flag
                        existing.spent_in_tx = None
                        logger.info(f"Cleared spent flag for UTXO: {utxo_key}")
            
            # Mark UTXOs as spent if they're in DB but not on blockchain
            for utxo_key, db_utxo in db_utxo_map.items():
                if utxo_key not in blockchain_utxo_keys and db_utxo.spent_in_tx is None:
                    # UTXO no longer on blockchain - mark as spent
                    db_utxo.spent_in_tx = "unknown"  # We don't know the spending tx
                    spent_count += 1
                    logger.info(f"Marked UTXO as spent: {utxo_key}")
            
            db.commit()
            logger.info(f"Synced UTXOs for {self.address}: {new_count} new, {spent_count} spent")
            return len(blockchain_utxos), new_count, spent_count
            
        except Exception as e:
            logger.error(f"Error syncing UTXOs to database: {e}")
            db.rollback()
            return 0, 0, 0
        finally:
            db.close() 