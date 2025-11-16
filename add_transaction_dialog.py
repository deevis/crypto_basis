from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QLineEdit, QComboBox, QFormLayout, QMessageBox, QDateTimeEdit)
from PyQt6.QtCore import Qt, QDateTime
from db_config import SessionLocal
from models import Transaction, OperationType
from sqlalchemy import distinct
import uuid

class AddTransactionDialog(QDialog):
    def __init__(self, wallet_name=None, currency=None, operation_type=None, transaction=None, parent=None):
        super().__init__(parent)
        self.session = SessionLocal()
        self.transaction = self.session.merge(transaction) if transaction else None
        
        self.setWindowTitle("Edit Transaction" if transaction else "Add Transaction")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        
        # Form layout
        form = QFormLayout()
        
        # Wallet selection
        self.wallet_combo = QComboBox()
        self.load_wallets()
        if wallet_name:
            index = self.wallet_combo.findText(wallet_name)
            if index >= 0:
                self.wallet_combo.setCurrentIndex(index)
        form.addRow("Wallet:", self.wallet_combo)
        
        # Currency selection
        self.currency_combo = QComboBox()
        self.load_currencies()
        if currency:
            index = self.currency_combo.findText(currency)
            if index >= 0:
                self.currency_combo.setCurrentIndex(index)
        form.addRow("Currency:", self.currency_combo)
        
        # Operation type
        self.type_combo = QComboBox()
        self.type_combo.addItems(["IN", "OUT"])
        if operation_type:
            self.type_combo.setCurrentText(operation_type)
        form.addRow("Type:", self.type_combo)
        
        # Amount
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Amount of cryptocurrency")
        form.addRow("Amount:", self.amount_input)
        
        # Cost Basis (for IN transactions)
        self.cost_basis_input = QLineEdit()
        self.cost_basis_input.setPlaceholderText("Cost basis per unit in USD")
        form.addRow("Cost Basis ($):", self.cost_basis_input)
        
        # Date/Time
        self.date_input = QDateTimeEdit(QDateTime.currentDateTime())
        self.date_input.setCalendarPopup(True)
        form.addRow("Date:", self.date_input)
        
        # Memo field
        self.memo_input = QLineEdit()
        self.memo_input.setPlaceholderText("Optional note about this transaction")
        form.addRow("Memo:", self.memo_input)
        
        layout.addLayout(form)
        
        # Connect signals
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_transaction)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        # Initial type setup
        self.on_type_changed(self.type_combo.currentText())
        
        # If editing, populate fields and disable some options
        if self.transaction:
            self.wallet_combo.setCurrentText(self.transaction.wallet_name)
            self.currency_combo.setCurrentText(self.transaction.currency_ticker)
            self.type_combo.setCurrentText(self.transaction.operation_type.value)
            self.amount_input.setText(f"{self.transaction.operation_amount:.8f}")
            if self.transaction.cost_basis:
                self.cost_basis_input.setText(f"{self.transaction.cost_basis:.2f}")
            self.date_input.setDateTime(QDateTime(self.transaction.operation_date))
            if self.transaction.memo:
                self.memo_input.setText(self.transaction.memo)
            
            # Disable type changing for existing transactions
            self.type_combo.setEnabled(False)
            self.wallet_combo.setEnabled(False)
            self.currency_combo.setEnabled(False)
    
    def load_wallets(self):
        wallets = self.session.query(distinct(Transaction.wallet_name))\
            .order_by(Transaction.wallet_name)\
            .all()
        
        self.wallet_combo.clear()
        for wallet in wallets:
            self.wallet_combo.addItem(wallet[0])
    
    def load_currencies(self):
        currencies = self.session.query(distinct(Transaction.currency_ticker))\
            .order_by(Transaction.currency_ticker)\
            .all()
        
        self.currency_combo.clear()
        for currency in currencies:
            self.currency_combo.addItem(currency[0])
    
    def on_type_changed(self, operation_type):
        """Enable/disable cost basis based on operation type"""
        is_in = operation_type == "IN"
        self.cost_basis_input.setEnabled(is_in)
        self.cost_basis_input.setPlaceholderText(
            "Cost basis per unit in USD" if is_in else "Not applicable for OUT transactions"
        )
    
    def save_transaction(self):
        try:
            # Validate inputs
            wallet = self.wallet_combo.currentText()
            currency = self.currency_combo.currentText()
            operation_type = OperationType(self.type_combo.currentText())
            
            try:
                amount = float(self.amount_input.text())
                if amount <= 0:
                    raise ValueError("Amount must be positive")
            except ValueError:
                raise ValueError("Invalid amount")
            
            cost_basis = 0
            if operation_type == OperationType.IN:
                try:
                    cost_basis = float(self.cost_basis_input.text())
                    if cost_basis <= 0:
                        raise ValueError("Cost basis must be positive")
                except ValueError:
                    raise ValueError("Invalid cost basis")
            
            # Create or update transaction record
            if self.transaction:
                # Update existing transaction
                transaction = self.transaction
                transaction.wallet_name = wallet
                transaction.currency_ticker = currency
                transaction.operation_type = operation_type
                transaction.operation_date = self.date_input.dateTime().toPyDateTime()
                transaction.operation_amount = amount
                transaction.cost_basis = cost_basis
                transaction.cost_basis_minus_fees = cost_basis
                transaction.countervalue_at_operation = amount * cost_basis if operation_type == OperationType.IN else 0
                transaction.available_to_spend = amount if operation_type == OperationType.IN else None
                transaction.memo = self.memo_input.text().strip() or None
                
                action_text = "Updated"
            else:
                # Create new transaction
                transaction = Transaction(
                    wallet_name=wallet,
                    countervalue_ticker="USD",
                    currency_ticker=currency,
                    operation_type=operation_type,
                    operation_date=self.date_input.dateTime().toPyDateTime(),
                    operation_amount=amount,
                    operation_fees=0.0,
                    cost_basis=cost_basis,
                    cost_basis_minus_fees=cost_basis,
                    status="Confirmed",
                    account_name="Manual Entry",
                    account_xpub="manual",
                    countervalue_at_operation=amount * cost_basis if operation_type == OperationType.IN else 0,
                    operation_hash=f"manual_{uuid.uuid4().hex}",
                    available_to_spend=amount if operation_type == OperationType.IN else None,
                    memo=self.memo_input.text().strip() or None
                )
                self.session.add(transaction)
                action_text = "Added"
            
            self.session.commit()
            
            QMessageBox.information(
                self,
                "Success",
                f"{action_text} {operation_type.value} transaction for {amount:.8f} {currency}"
            )
            self.accept()
            
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
        except Exception as e:
            self.session.rollback()
            QMessageBox.critical(self, "Error", f"Failed to save transaction: {str(e)}") 