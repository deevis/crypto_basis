from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                           QPushButton, QListWidget, QFileDialog, QListWidgetItem)
from PyQt6.QtCore import Qt
from db_config import get_db
from models import Transaction
import csv
from sqlalchemy import distinct

class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Transactions")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        # Coin selection section
        layout.addWidget(QLabel("Select Coins to Export:"))
        
        self.coin_list = QListWidget()
        self.coin_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.coin_list)
        
        # Load available coins
        self.load_coins()
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.select_all_coins)
        button_layout.addWidget(self.select_all_button)
        
        self.clear_button = QPushButton("Clear Selection")
        self.clear_button.clicked.connect(self.clear_selection)
        button_layout.addWidget(self.clear_button)
        
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_transactions)
        button_layout.addWidget(self.export_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
    
    def load_coins(self):
        db = next(get_db())
        coins = db.query(distinct(Transaction.currency_ticker)).all()
        for coin in sorted(coins):
            item = QListWidgetItem(coin[0])
            self.coin_list.addItem(item)
    
    def select_all_coins(self):
        for i in range(self.coin_list.count()):
            self.coin_list.item(i).setSelected(True)
    
    def clear_selection(self):
        for i in range(self.coin_list.count()):
            self.coin_list.item(i).setSelected(False)
    
    def export_transactions(self):
        selected_coins = [item.text() for item in self.coin_list.selectedItems()]
        if not selected_coins:
            return
        
        # Get export file location
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Export Transactions",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if not file_name:
            return
            
        try:
            db = next(get_db())
            transactions = db.query(Transaction).filter(
                Transaction.currency_ticker.in_(selected_coins)
            ).order_by(
                Transaction.currency_ticker,
                Transaction.wallet_name,
                Transaction.operation_date
            ).all()
            
            with open(file_name, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                # Write header
                writer.writerow([
                    'Wallet', 'Coin', 'Type', 'Date', 'Amount', 'Cost Basis',
                    'Cost Basis (minus fees)', 'Fees', 'Status', 'Account Name',
                    'Account xpub', 'Operation Hash', 'Linked Transaction'
                ])
                
                # Write transactions
                for tx in transactions:
                    writer.writerow([
                        tx.wallet_name,
                        tx.currency_ticker,
                        tx.operation_type.value,
                        tx.operation_date.strftime('%Y-%m-%dT%H:%M:%S'),
                        tx.operation_amount,
                        tx.cost_basis,
                        tx.cost_basis_minus_fees,
                        tx.operation_fees,
                        tx.status,
                        tx.account_name,
                        tx.account_xpub,
                        tx.operation_hash,
                        tx.linked_transaction_id
                    ])
            
            self.accept()
            
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export transactions: {str(e)}"
            ) 