from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QComboBox, QMessageBox, QFormLayout, QLineEdit, QDateTimeEdit)
from PyQt6.QtCore import Qt, QDateTime
from db_config import SessionLocal
from models import Exchange, ExchangeTransfer, Transaction, TransactionFulfillment
from datetime import datetime

class ExchangeTransferDialog(QDialog):
    def __init__(self, out_transaction_id, parent=None, transfer=None):
        super().__init__(parent)
        self.session = SessionLocal()
        self.out_transaction_id = out_transaction_id
        self.out_transaction = self.session.query(Transaction).get(out_transaction_id)
        
        # If we're editing, get a fresh copy of the transfer in our session
        if transfer:
            self.transfer = self.session.merge(transfer)
        else:
            self.transfer = None
        
        self.setWindowTitle(f"{'Edit' if transfer else 'Create'} Exchange Transfer - {self.out_transaction.operation_amount} {self.out_transaction.currency_ticker}")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        
        # Transaction details section
        details_layout = QHBoxLayout()
        details_layout.addWidget(QLabel(f"Amount: {self.out_transaction.operation_amount} {self.out_transaction.currency_ticker}"))
        details_layout.addWidget(QLabel(f"Cost Basis: ${self.out_transaction.cost_basis:.2f}"))
        details_layout.addWidget(QLabel(f"Date: {self.out_transaction.operation_date.strftime('%Y-%m-%d %H:%M')}"))
        layout.addLayout(details_layout)
        
        # Form for transfer details
        form = QFormLayout()
        
        # Exchange selection
        self.exchange_combo = QComboBox()
        self.load_exchanges()
        form.addRow("Exchange:", self.exchange_combo)
        
        # Sale details (optional)
        self.sale_amount = QLineEdit()
        self.sale_amount.setPlaceholderText(f"Max: {self.out_transaction.operation_amount}")
        self.sale_price = QLineEdit()
        self.sale_price.setPlaceholderText("Price per unit")
        
        self.sale_date = QDateTimeEdit(QDateTime.currentDateTime())
        self.sale_date.setCalendarPopup(True)
        
        form.addRow("Sale Amount:", self.sale_amount)
        form.addRow("Sale Price ($):", self.sale_price)
        form.addRow("Sale Date:", self.sale_date)
        
        # Add fee field after sale price
        self.fee_input = QLineEdit()
        self.fee_input.setPlaceholderText("Exchange fee in USD")
        form.addRow("Fee ($):", self.fee_input)
        
        # Read-only realized gain field
        self.realized_gain = QLineEdit()
        self.realized_gain.setReadOnly(True)
        form.addRow("Realized Gain ($):", self.realized_gain)
        
        # Connect signals for auto-calculation
        self.sale_amount.textChanged.connect(self.calculate_realized_gain)
        self.sale_price.textChanged.connect(self.calculate_realized_gain)
        self.fee_input.textChanged.connect(self.calculate_realized_gain)
        
        # Add recalculate button if editing
        if self.transfer:
            recalc_button = QPushButton("Recalculate from Fulfillments")
            recalc_button.clicked.connect(self.update_cost_basis_from_fulfillments)
            form.addRow("", recalc_button)
        
        layout.addLayout(form)
        
        # Buttons
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")
        
        save_button.clicked.connect(self.save_transfer)
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        # If editing, populate fields with existing data
        if transfer:
            # Set exchange
            index = self.exchange_combo.findData(transfer.exchange_id)
            if index >= 0:
                self.exchange_combo.setCurrentIndex(index)
            
            # Set sale details
            if transfer.sale_amount:
                self.sale_amount.setText(f"{transfer.sale_amount}")
            if transfer.sale_price:
                self.sale_price.setText(f"{transfer.sale_price}")
            if transfer.sale_date:
                self.sale_date.setDateTime(transfer.sale_date)
            
            # Set fee
            if transfer.fee:
                self.fee_input.setText(f"{transfer.fee:.2f}")
    
    def load_exchanges(self):
        """Refresh the list of available exchanges"""
        current_exchange_id = self.exchange_combo.currentData()  # Remember current selection
        
        exchanges = self.session.query(Exchange)\
            .filter(Exchange.active == True)\
            .order_by(Exchange.name)\
            .all()
        
        self.exchange_combo.clear()
        for exchange in exchanges:
            self.exchange_combo.addItem(exchange.name, exchange.id)
            
        # Restore previous selection if it still exists
        if current_exchange_id:
            index = self.exchange_combo.findData(current_exchange_id)
            if index >= 0:
                self.exchange_combo.setCurrentIndex(index)
    
    def calculate_realized_gain(self):
        try:
            sale_amount = float(self.sale_amount.text() or 0)
            sale_price = float(self.sale_price.text() or 0)
            fee = float(self.fee_input.text() or 0)
            
            if sale_amount and sale_price:
                # Calculate total sale value
                sale_value = sale_amount * sale_price
                
                # Calculate cost basis for the sold amount
                cost_basis_per_unit = self.out_transaction.cost_basis
                cost_basis_for_amount = sale_amount * cost_basis_per_unit
                
                # Calculate realized gain/loss including fee
                realized_gain = sale_value - cost_basis_for_amount - fee
                
                self.realized_gain.setText(f"${realized_gain:,.2f}")
            else:
                self.realized_gain.clear()
                
        except ValueError:
            self.realized_gain.clear()
    
    def save_transfer(self):
        try:
            if not self.transfer:
                exchange_id = self.exchange_combo.currentData()
                if not exchange_id:
                    raise ValueError("Please select an exchange")
                
                # Get or create transfer record
                transfer = ExchangeTransfer(
                    exchange_id=exchange_id,
                    out_transaction_id=self.out_transaction_id,
                    fee=float(self.fee_input.text() or 0)
                )
                self.session.add(transfer)  # Only add new transfers
                
                # Update exchange if changed
                transfer.exchange_id = exchange_id
                
                # Add/update sale details if provided
                if self.sale_amount.text().strip() and self.sale_price.text().strip():
                    try:
                        sale_amount = float(self.sale_amount.text())
                        sale_price = float(self.sale_price.text())
                        
                        if sale_amount > self.out_transaction.operation_amount:
                            raise ValueError("Sale amount cannot exceed transfer amount")
                        
                        if sale_amount <= 0 or sale_price <= 0:
                            raise ValueError("Sale amount and price must be positive")
                        
                        transfer.sale_amount = sale_amount
                        transfer.sale_price = sale_price
                        
                        # Recalculate all derived values
                        sale_value = sale_amount * sale_price
                        
                        # Get acquisition details
                        acq_price, acq_date = transfer.calculate_acquisition_details(self.session)
                        transfer.acquisition_price = acq_price
                        transfer.acquisition_date = acq_date
                        
                        # Calculate realized gain using acquisition price
                        if acq_price:
                            cost_basis = sale_amount * acq_price
                            transfer.realized_gain = sale_value - cost_basis - transfer.fee
                        
                        # Update term type
                        transfer.term_type = transfer.calculate_term_type(self.session)
                        
                    except ValueError as e:
                        raise ValueError(f"Invalid sale details: {str(e)}")
                
            else:
                # Update existing transfer
                self.transfer.sale_date = self.sale_date.dateTime().toPyDateTime() if self.sale_date.isEnabled() else None
                self.transfer.sale_amount = float(self.sale_amount.text()) if self.sale_amount.text() else None
                self.transfer.sale_price = float(self.sale_price.text()) if self.sale_price.text() else None
                self.transfer.fee = float(self.fee_input.text() or 0)
                
                # Recalculate cost basis from fulfillments if needed
                if not self.out_transaction.cost_basis or self.out_transaction.cost_basis == 0:
                    self.update_cost_basis_from_fulfillments()
                
                # Calculate realized gain
                if self.transfer.sale_date and self.transfer.sale_amount and self.transfer.sale_price:
                    sale_value = self.transfer.sale_amount * self.transfer.sale_price
                    cost_basis = self.transfer.sale_amount * self.out_transaction.cost_basis
                    self.transfer.realized_gain = sale_value - cost_basis - self.transfer.fee
                    
                    # Recalculate term type
                    self.transfer.term_type = self.transfer.calculate_term_type(self.session)
                
            self.session.commit()
            
            QMessageBox.information(
                self,
                "Success",
                "Exchange transfer saved successfully!"
            )
            self.accept()
            
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
        except Exception as e:
            self.session.rollback()
            QMessageBox.critical(self, "Error", str(e))
    
    def update_cost_basis_from_fulfillments(self):
        """Update the OUT transaction's cost basis from its fulfillments"""
        fulfillments = self.session.query(TransactionFulfillment)\
            .filter(TransactionFulfillment.out_transaction_id == self.out_transaction_id)\
            .all()
        
        if not fulfillments:
            raise ValueError("Transaction must be fulfilled before sending to exchange")
        
        total_amount = 0
        total_cost = 0
        
        for fulfillment in fulfillments:
            total_amount += fulfillment.in_transaction_amount
            total_cost += fulfillment.in_transaction_amount * fulfillment.in_transaction_cost_basis
        
        if total_amount > 0:
            weighted_cost_basis = total_cost / total_amount
            self.out_transaction.cost_basis = weighted_cost_basis
            self.out_transaction.cost_basis_minus_fees = weighted_cost_basis
            
            QMessageBox.information(
                self,
                "Cost Basis Updated",
                f"Updated transaction cost basis to ${weighted_cost_basis:.2f} based on fulfillments"
            ) 