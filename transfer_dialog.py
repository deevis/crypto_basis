from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView, QWidget)
from PyQt6.QtCore import Qt
from db_config import SessionLocal
from models import Transaction, WalletTransfer, OperationType, TransactionFulfillment
from sqlalchemy import and_, func

class TransferDialog(QDialog):
    def __init__(self, out_transaction_id, parent=None):
        super().__init__(parent)
        self.out_transaction_id = out_transaction_id
        self.session = SessionLocal()
        
        # Load the OUT transaction
        self.out_transaction = self.session.query(Transaction).get(out_transaction_id)
        
        # Check if transaction is fully fulfilled
        total_percent = self.session.query(func.sum(TransactionFulfillment.out_transaction_percent_filled))\
            .filter(TransactionFulfillment.out_transaction_id == self.out_transaction_id)\
            .scalar() or 0
            
        if abs(100 - total_percent) > 0.01:
            QMessageBox.warning(
                self,
                "Cannot Link Transfer",
                "Transaction must be 100% fulfilled with source transactions before linking to another wallet."
            )
            self.reject()
            return
        
        self.setWindowTitle(f"Link Wallet Transfer - {self.out_transaction.operation_amount} {self.out_transaction.currency_ticker}")
        self.setModal(True)
        self.setMinimumWidth(800)
        self.setMinimumHeight(500)
        
        layout = QVBoxLayout(self)
        
        # OUT Transaction details
        details_layout = QHBoxLayout()
        details_layout.addWidget(QLabel(f"OUT Transaction: {self.out_transaction.operation_amount} {self.out_transaction.currency_ticker}"))
        details_layout.addWidget(QLabel(f"From Wallet: {self.out_transaction.wallet_name}"))
        details_layout.addWidget(QLabel(f"Date: {self.out_transaction.operation_date.strftime('%Y-%m-%d %H:%M')}"))
        details_layout.addWidget(QLabel(f"Cost Basis: ${self.out_transaction.cost_basis:.2f}"))
        layout.addLayout(details_layout)
        
        # Available IN Transactions table
        layout.addWidget(QLabel("Available IN Transactions in Other Wallets:"))
        self.available_table = QTableWidget()
        self.setup_available_table()
        layout.addWidget(self.available_table)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close_dialog)
        layout.addWidget(close_button)
        
        # Load data
        self.load_available_transactions()
        
    def setup_available_table(self):
        headers = ["ID", "Wallet", "Date", "Amount", "Status", "Actions"]
        self.available_table.setColumnCount(len(headers))
        self.available_table.setHorizontalHeaderLabels(headers)
        self.available_table.setSortingEnabled(True)
        header = self.available_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
    def load_available_transactions(self):
        # Get IN transactions from other wallets with similar amount
        # Allow for 0.1% difference in amounts
        target_amount = self.out_transaction.operation_amount
        tolerance = target_amount * 0.001  # 0.1% tolerance
        
        available_txs = self.session.query(Transaction).filter(
            and_(
                Transaction.wallet_name != self.out_transaction.wallet_name,  # Different wallet
                Transaction.currency_ticker == self.out_transaction.currency_ticker,  # Same currency
                Transaction.operation_type == OperationType.IN,
                Transaction.operation_amount.between(  # Amount within tolerance
                    target_amount - tolerance,
                    target_amount + tolerance
                ),
                ~Transaction.id.in_(  # Not already linked to a transfer
                    self.session.query(WalletTransfer.in_transaction_id)
                )
            )
        ).order_by(Transaction.operation_date).all()
        
        self.available_table.setRowCount(len(available_txs))
        for i, tx in enumerate(available_txs):
            # Add a note if amounts don't match exactly
            amount_diff = abs(tx.operation_amount - self.out_transaction.operation_amount)
            if amount_diff > 0:
                diff_percent = (amount_diff / self.out_transaction.operation_amount) * 100
                amount_text = f"{tx.operation_amount:.8f} (Δ {diff_percent:.3f}%)"
            else:
                amount_text = f"{tx.operation_amount:.8f}"
            
            items = [
                QTableWidgetItem(str(tx.id)),
                QTableWidgetItem(tx.wallet_name),
                QTableWidgetItem(tx.operation_date.strftime('%Y-%m-%d %H:%M')),
                QTableWidgetItem(amount_text),
                QTableWidgetItem(tx.status)
            ]
            
            for col, item in enumerate(items):
                self.available_table.setItem(i, col, item)
            
            # Add Link button with reconciliation option if needed
            button_widget = QWidget()
            button_layout = QHBoxLayout(button_widget)
            button_layout.setContentsMargins(0, 0, 0, 0)
            
            if amount_diff > 0:
                reconcile_button = QPushButton("Link & Reconcile")
                reconcile_button.clicked.connect(lambda checked, tx=tx: self.reconcile_and_link(tx))
                button_layout.addWidget(reconcile_button)
            else:
                link_button = QPushButton("Link Transfer")
                link_button.clicked.connect(lambda checked, tx=tx: self.link_transfer(tx))
                button_layout.addWidget(link_button)
            
            self.available_table.setCellWidget(i, len(items), button_widget)
    
    def reconcile_and_link(self, in_transaction):
        """Link transfers with different amounts and reconcile the difference"""
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Reconcile Amounts")
        
        diff = abs(in_transaction.operation_amount - self.out_transaction.operation_amount)
        diff_percent = (diff / self.out_transaction.operation_amount) * 100
        
        msg.setText(f"The amounts differ by {diff:.8f} ({diff_percent:.3f}%)\n\n"
                   f"OUT: {self.out_transaction.operation_amount:.8f}\n"
                   f"IN:  {in_transaction.operation_amount:.8f}\n\n"
                   "How would you like to handle this difference?")
        
        adjust_in = msg.addButton("Adjust IN Amount", QMessageBox.ButtonRole.ActionRole)
        adjust_out = msg.addButton("Adjust OUT Amount", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        
        msg.exec()
        
        if msg.clickedButton() == adjust_in:
            in_transaction.operation_amount = self.out_transaction.operation_amount
            self.link_transfer(in_transaction)
        elif msg.clickedButton() == adjust_out:
            self.out_transaction.operation_amount = in_transaction.operation_amount
            self.link_transfer(in_transaction)
    
    def link_transfer(self, in_transaction):
        try:
            # Create transfer record
            transfer = WalletTransfer(
                out_transaction_id=self.out_transaction_id,
                in_transaction_id=in_transaction.id,
                amount=self.out_transaction.operation_amount
            )
            
            # Update the IN transaction's cost basis to match the OUT transaction
            in_transaction.cost_basis = self.out_transaction.cost_basis
            
            self.session.add(transfer)
            self.session.commit()
            
            QMessageBox.information(
                self,
                "Success",
                f"Linked transfer between wallets {self.out_transaction.wallet_name} and {in_transaction.wallet_name}\n"
                f"Updated IN transaction cost basis to ${self.out_transaction.cost_basis:.2f}"
            )
            self.accept()
            
        except Exception as e:
            self.session.rollback()
            QMessageBox.critical(self, "Error", f"Failed to link transfer: {str(e)}")
    
    def close_dialog(self):
        self.session.close()
        self.reject() 