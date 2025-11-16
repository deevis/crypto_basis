import csv
from datetime import datetime
from models import Transaction, OperationType
from db_config import SessionLocal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QDialogButtonBox

class UTXOImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BTC UTXO Import Settings")
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # Wallet Name input
        layout.addWidget(QLabel("Wallet Name:"))
        self.wallet_name = QLineEdit()
        self.wallet_name.setPlaceholderText("Enter wallet name")
        layout.addWidget(self.wallet_name)
        
        # Account Name input
        layout.addWidget(QLabel("Account Name:"))
        self.account_name = QLineEdit()
        self.account_name.setPlaceholderText("Enter account name")
        layout.addWidget(self.account_name)
        
        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
    def get_values(self):
        return {
            'wallet_name': self.wallet_name.text(),
            'account_name': self.account_name.text()
        }

def import_btc_utxos(file_path, wallet_name, account_name):
    session = SessionLocal()
    
    with open(file_path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Convert the date format
            date = datetime.strptime(row['final_date'], '%Y-%m-%dT%H:%M:%S')
            amount = float(row['final_amount_btc'])
            cost_basis = float(row['weighted_cost_basis_usd_per_btc'])
            
            transaction = Transaction(
                wallet_name=wallet_name,
                countervalue_ticker="USD",
                currency_ticker="BTC",
                operation_type=OperationType.IN,
                operation_date=date,
                operation_amount=amount,
                operation_fees=0.0,  # Not provided in UTXO format
                cost_basis_minus_fees=cost_basis,
                cost_basis=cost_basis,
                status="Confirmed",
                account_name=account_name,
                account_xpub=row['final_address'],
                countervalue_at_operation=float(row['total_cost_usd']),
                operation_hash=row['final_txid'],
                available_to_spend=amount  # Set for IN transactions
            )
            session.add(transaction)
            
        session.commit() 