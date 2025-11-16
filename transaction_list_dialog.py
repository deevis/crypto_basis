from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox)
from PyQt6.QtCore import Qt
from db_config import SessionLocal
from models import Transaction
from btc_service import BTCService
from tx_details_dialog import TransactionDetailsDialog

class TransactionListDialog(QDialog):
    def __init__(self, parent=None):
        # ... existing init code ...
        
    def setup_table(self):
        # ... existing setup code ...
        
        # Add TX Info button for BTC transactions
        if tx.currency_ticker == "BTC" and tx.operation_hash:
            tx_info_btn = QPushButton("TX Info")
            tx_info_btn.clicked.connect(lambda: self.show_tx_info(tx.operation_hash))
            self.table.setCellWidget(row, col_count - 1, tx_info_btn)
    
    def show_tx_info(self, txid):
        """Show transaction details dialog for a BTC transaction"""
        try:
            btc_service = BTCService()
            tx_data = btc_service.get_raw_transaction_info(txid)
            
            dialog = TransactionDetailsDialog(tx_data, address=None)  # No address verification needed
            dialog.exec()
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to get transaction info: {str(e)}"
            ) 