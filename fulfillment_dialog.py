from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView, QWidget)
from PyQt6.QtCore import Qt
from db_config import SessionLocal
from models import Transaction, TransactionFulfillment, OperationType
from sqlalchemy import and_, func

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            self_value = float(self.text().replace('$', '').replace(',', '').replace('%', ''))
            other_value = float(other.text().replace('$', '').replace(',', '').replace('%', ''))
            return self_value < other_value
        except ValueError:
            return super().__lt__(other)

class FulfillmentDialog(QDialog):
    def __init__(self, out_transaction_id, parent=None):
        super().__init__(parent)
        self.out_transaction_id = out_transaction_id
        self.session = SessionLocal()
        
        # Load the OUT transaction
        self.out_transaction = self.session.query(Transaction).get(out_transaction_id)
        
        self.setWindowTitle(f"Manage Fulfillments - {self.out_transaction.operation_amount} {self.out_transaction.currency_ticker}")
        self.setModal(True)
        self.setMinimumWidth(1000)
        self.setMinimumHeight(600)
        
        layout = QVBoxLayout(self)
        
        # OUT Transaction details
        details_layout = QHBoxLayout()
        details_layout.addWidget(QLabel(f"OUT Transaction: {self.out_transaction.operation_amount} {self.out_transaction.currency_ticker}"))
        details_layout.addWidget(QLabel(f"Wallet: {self.out_transaction.wallet_name}"))
        details_layout.addWidget(QLabel(f"Date: {self.out_transaction.operation_date.strftime('%Y-%m-%d %H:%M')}"))
        layout.addLayout(details_layout)
        
        # Progress and cost basis section
        progress_layout = QVBoxLayout()
        self.progress_label = QLabel()
        self.cost_basis_label = QLabel()
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.cost_basis_label)
        layout.addLayout(progress_layout)
        
        # Update cost basis button (initially hidden)
        self.update_button = QPushButton("Update OUT Cost Basis and Close")
        self.update_button.clicked.connect(self.update_cost_basis_and_close)
        self.update_button.setVisible(False)  # Hidden by default
        layout.addWidget(self.update_button)
        
        # Available IN Transactions table
        layout.addWidget(QLabel("Available IN Transactions:"))
        self.available_table = QTableWidget()
        self.setup_available_table()
        layout.addWidget(self.available_table)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.link_button = QPushButton("Link Selected")
        self.link_button.clicked.connect(self.link_selected)
        button_layout.addWidget(self.link_button)
        layout.addLayout(button_layout)
        
        # Current Fulfillments table
        layout.addWidget(QLabel("Current Fulfillments:"))
        self.fulfillments_table = QTableWidget()
        self.setup_fulfillments_table()
        layout.addWidget(self.fulfillments_table)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close_dialog)
        layout.addWidget(close_button)
        
        # Load data
        self.load_data()
        
    def setup_available_table(self):
        headers = ["ID", "Date", "Amount", "Available", "Cost Basis", "Select Amount", "Actions"]
        self.available_table.setColumnCount(len(headers))
        self.available_table.setHorizontalHeaderLabels(headers)
        self.available_table.setSortingEnabled(True)
        header = self.available_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
    def setup_fulfillments_table(self):
        headers = ["ID", "Date", "Amount Used", "Cost Basis", "Percent of OUT", ""]
        self.fulfillments_table.setColumnCount(len(headers))
        self.fulfillments_table.setHorizontalHeaderLabels(headers)
        self.fulfillments_table.setSortingEnabled(True)
        header = self.fulfillments_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        
    def load_data(self):
        self.load_available_transactions()
        self.load_current_fulfillments()
        self.update_progress_label()
        
    def load_available_transactions(self):
        # Get IN transactions from same wallet with available amount and before OUT date
        available_txs = self.session.query(Transaction).filter(
            and_(
                Transaction.wallet_name == self.out_transaction.wallet_name,
                Transaction.currency_ticker == self.out_transaction.currency_ticker,
                Transaction.operation_type == OperationType.IN,
                Transaction.available_to_spend > 0,
                Transaction.operation_date <= self.out_transaction.operation_date
            )
        ).order_by(Transaction.operation_date).all()
        
        self.available_table.setRowCount(len(available_txs))
        for i, tx in enumerate(available_txs):
            # Create button container widget
            button_widget = QWidget()
            button_layout = QHBoxLayout(button_widget)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(2)
            
            # Add buttons
            select_button = QPushButton("Select")
            select_full_button = QPushButton("Full")
            select_remainder_button = QPushButton("Remainder")
            
            select_button.clicked.connect(lambda checked, tx=tx: self.select_transaction(tx))
            select_full_button.clicked.connect(lambda checked, tx=tx: self.select_full_amount(tx))
            select_remainder_button.clicked.connect(lambda checked, tx=tx: self.select_remainder_amount(tx))
            
            button_layout.addWidget(select_button)
            button_layout.addWidget(select_full_button)
            button_layout.addWidget(select_remainder_button)
            
            items = [
                QTableWidgetItem(str(tx.id)),
                QTableWidgetItem(tx.operation_date.strftime('%Y-%m-%d %H:%M')),
                NumericTableWidgetItem(f"{tx.operation_amount:.8f}"),
                NumericTableWidgetItem(f"{tx.available_to_spend:.8f}"),
                NumericTableWidgetItem(f"${tx.cost_basis:,.2f}"),
                QTableWidgetItem("0.0")  # Editable amount to use
            ]
            
            for col, item in enumerate(items):
                self.available_table.setItem(i, col, item)
                if col == 5:  # Make the amount column editable
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            
            self.available_table.setCellWidget(i, len(items), button_widget)
    
    def select_transaction(self, in_transaction):
        try:
            # Get the amount to use from the editable cell
            row = next(i for i in range(self.available_table.rowCount()) 
                      if self.available_table.item(i, 0).text() == str(in_transaction.id))
            amount_str = self.available_table.item(row, 5).text()
            amount_to_use = float(amount_str)
            
            # Validate amount
            if amount_to_use <= 0:
                raise ValueError("Amount must be greater than 0")
            if amount_to_use > in_transaction.available_to_spend:
                raise ValueError("Amount exceeds available balance")
            
            # Calculate percent of OUT transaction this fulfills
            percent_filled = (amount_to_use / self.out_transaction.operation_amount) * 100
            
            # Check if total percent would exceed 100%
            current_total = self.session.query(func.sum(TransactionFulfillment.out_transaction_percent_filled))\
                .filter(TransactionFulfillment.out_transaction_id == self.out_transaction_id)\
                .scalar() or 0
                
            if current_total + percent_filled > 100:
                raise ValueError("This would exceed 100% fulfillment")
            
            # Create fulfillment record
            fulfillment = TransactionFulfillment(
                out_transaction_id=self.out_transaction_id,
                in_transaction_id=in_transaction.id,
                in_transaction_amount=amount_to_use,
                in_transaction_cost_basis=in_transaction.cost_basis,
                out_transaction_percent_filled=percent_filled
            )
            
            # Update available_to_spend on IN transaction
            in_transaction.available_to_spend -= amount_to_use
            
            self.session.add(fulfillment)
            self.session.commit()
            
            # Update the OUT transaction's cost basis
            self.update_cost_basis()
            
            # Refresh the display
            self.load_data()
            
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
        except Exception as e:
            self.session.rollback()
            QMessageBox.critical(self, "Error", f"Failed to link transaction: {str(e)}")
    
    def load_current_fulfillments(self):
        fulfillments = self.session.query(TransactionFulfillment).filter(
            TransactionFulfillment.out_transaction_id == self.out_transaction_id
        ).all()
        
        self.fulfillments_table.setRowCount(len(fulfillments))
        for i, fulfillment in enumerate(fulfillments):
            remove_button = QPushButton("Remove")
            remove_button.clicked.connect(lambda checked, f=fulfillment: self.remove_fulfillment(f))
            
            items = [
                QTableWidgetItem(str(fulfillment.in_transaction_id)),
                QTableWidgetItem(fulfillment.in_transaction.operation_date.strftime('%Y-%m-%d %H:%M')),
                NumericTableWidgetItem(f"{fulfillment.in_transaction_amount:.8f}"),
                NumericTableWidgetItem(f"${fulfillment.in_transaction_cost_basis:,.2f}"),
                NumericTableWidgetItem(f"{fulfillment.out_transaction_percent_filled:.2f}%")
            ]
            
            for col, item in enumerate(items):
                self.fulfillments_table.setItem(i, col, item)
            self.fulfillments_table.setCellWidget(i, len(items), remove_button)
    
    def update_progress_label(self):
        # Get total percent filled and calculate weighted average cost basis
        result = self.session.query(
            func.sum(TransactionFulfillment.out_transaction_percent_filled).label('total_percent'),
            func.sum(TransactionFulfillment.in_transaction_amount * TransactionFulfillment.in_transaction_cost_basis).label('total_cost'),
            func.sum(TransactionFulfillment.in_transaction_amount).label('total_amount')
        ).filter(
            TransactionFulfillment.out_transaction_id == self.out_transaction_id
        ).first()
        
        total_percent = result.total_percent or 0
        total_cost = result.total_cost or 0
        total_amount = result.total_amount or 0
        
        # Calculate amounts for progress
        total_out_amount = self.out_transaction.operation_amount
        filled_amount = (total_percent / 100) * total_out_amount
        remaining_amount = total_out_amount - filled_amount
        
        # Calculate weighted average cost basis
        weighted_cost_basis = (total_cost / total_amount) if total_amount > 0 else 0
        
        # Create detailed progress message
        progress_text = (
            f"Fulfillment Progress: {total_percent:.2f}% "
            f"({filled_amount:.8f} out of {total_out_amount:.8f} {self.out_transaction.currency_ticker} "
            f"accounted for ({remaining_amount:.8f} remaining))"
        )
        
        cost_basis_text = (
            f"Computed Cost Basis: ${weighted_cost_basis:.2f} "
            f"(current: ${self.out_transaction.cost_basis:.2f})"
        )
        
        self.progress_label.setText(progress_text)
        self.cost_basis_label.setText(cost_basis_text)
        
        # Set colors and show/hide update button
        is_complete = abs(100 - total_percent) < 0.01
        self.progress_label.setStyleSheet("color: " + ("green" if is_complete else "red"))
        self.update_button.setVisible(is_complete)
    
    def update_cost_basis_and_close(self):
        try:
            # Calculate new weighted average cost basis
            result = self.session.query(
                func.sum(TransactionFulfillment.in_transaction_amount * TransactionFulfillment.in_transaction_cost_basis).label('total_cost'),
                func.sum(TransactionFulfillment.in_transaction_amount).label('total_amount')
            ).filter(
                TransactionFulfillment.out_transaction_id == self.out_transaction_id
            ).first()
            
            total_cost = result.total_cost or 0
            total_amount = result.total_amount or 0
            
            if total_amount > 0:
                # Update the OUT transaction's cost basis
                weighted_cost_basis = total_cost / total_amount
                self.out_transaction.cost_basis = weighted_cost_basis
                self.out_transaction.cost_basis_minus_fees = weighted_cost_basis  # Since we don't track fees for fulfillments
                self.session.commit()
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"Updated OUT transaction cost basis to ${weighted_cost_basis:.2f}"
                )
                self.accept()
            
        except Exception as e:
            self.session.rollback()
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to update cost basis: {str(e)}"
            )
    
    def link_selected(self):
        # Implementation for linking selected transactions
        pass
        
    def remove_fulfillment(self, fulfillment):
        try:
            # Restore available_to_spend on IN transaction
            in_transaction = self.session.query(Transaction).get(fulfillment.in_transaction_id)
            in_transaction.available_to_spend += fulfillment.in_transaction_amount
            
            # Delete the fulfillment
            self.session.delete(fulfillment)
            self.session.commit()
            
            # Update the OUT transaction's cost basis
            self.update_cost_basis()
            
            # Refresh the display
            self.load_data()
            
        except Exception as e:
            self.session.rollback()
            QMessageBox.critical(self, "Error", f"Failed to remove fulfillment: {str(e)}")
        
    def close_dialog(self):
        self.session.close()
        self.accept() 
    
    def select_full_amount(self, in_transaction):
        """Select the full available amount from the IN transaction"""
        row = next(i for i in range(self.available_table.rowCount()) 
                  if self.available_table.item(i, 0).text() == str(in_transaction.id))
        
        # Set the amount to the full available amount
        amount_item = self.available_table.item(row, 5)
        amount_item.setText(str(in_transaction.available_to_spend))
        
        # Process the selection
        self.select_transaction(in_transaction)
    
    def select_remainder_amount(self, in_transaction):
        """Select the amount needed to complete the OUT transaction"""
        current_total = self.session.query(func.sum(TransactionFulfillment.out_transaction_percent_filled))\
            .filter(TransactionFulfillment.out_transaction_id == self.out_transaction_id)\
            .scalar() or 0
        
        if current_total >= 100:
            QMessageBox.warning(self, "Warning", "Transaction is already fully fulfilled")
            return
        
        # Calculate remaining amount needed
        remaining_percent = 100 - current_total
        remaining_amount = (remaining_percent / 100) * self.out_transaction.operation_amount
        
        # Use either the remaining amount needed or the available amount, whichever is smaller
        amount_to_use = min(remaining_amount, in_transaction.available_to_spend)
        
        # Set the amount in the table
        row = next(i for i in range(self.available_table.rowCount()) 
                  if self.available_table.item(i, 0).text() == str(in_transaction.id))
        amount_item = self.available_table.item(row, 5)
        amount_item.setText(str(amount_to_use))
        
        # Process the selection
        self.select_transaction(in_transaction) 

    def update_cost_basis(self):
        """Update the OUT transaction's cost basis based on fulfillments"""
        try:
            # Get all fulfillments for this transaction
            fulfillments = self.session.query(TransactionFulfillment)\
                .filter(TransactionFulfillment.out_transaction_id == self.out_transaction_id)\
                .all()
            
            if not fulfillments:
                return
            
            # Calculate weighted average cost basis
            total_amount = 0
            total_cost = 0
            
            for fulfillment in fulfillments:
                total_amount += fulfillment.in_transaction_amount
                total_cost += fulfillment.in_transaction_amount * fulfillment.in_transaction_cost_basis
            
            # Update OUT transaction cost basis
            if total_amount > 0:
                weighted_cost_basis = total_cost / total_amount
                self.out_transaction.cost_basis = weighted_cost_basis
                self.out_transaction.cost_basis_minus_fees = weighted_cost_basis  # Since we don't track fees for fulfillments
                
                self.session.commit()
                print(f"Updated OUT transaction cost basis to: ${weighted_cost_basis:.2f}")
        
        except Exception as e:
            print(f"Error updating cost basis: {e}")
            self.session.rollback() 