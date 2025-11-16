from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QLineEdit, QComboBox, QFormLayout, QMessageBox, QDateTimeEdit,
                           QProgressBar)
from PyQt6.QtCore import Qt, QDateTime, QThread, pyqtSignal
from db_config import SessionLocal
from models import Transaction, OperationType, Exchange
from btc_service import BTCService
from datetime import datetime
import threading
import logging

logger = logging.getLogger(__name__)

# Create a worker thread for blockchain scanning
class ScanWorker(QThread):
    progress = pyqtSignal(str)  # Emit progress updates
    finished = pyqtSignal(dict)  # Emit result
    error = pyqtSignal(str)      # Emit errors
    
    def __init__(self, btc_service, address, expected_date, txid=None):
        super().__init__()
        self.btc_service = btc_service
        self.address = address
        self.expected_date = expected_date
        self.txid = txid
        self.abort = False
    
    def run(self):
        try:
            # Hook up the progress logger
            def progress_callback(msg):
                self.progress.emit(msg)
                return not self.abort  # Return False to stop scanning
            
            self.btc_service.progress_callback = progress_callback
            result = self.btc_service.get_transaction_details(self.address, self.expected_date, self.txid)
            if not self.abort:
                self.finished.emit(result)
        except Exception as e:
            if not self.abort:
                self.error.emit(str(e))

class AddBTCDialog(QDialog):
    def __init__(self, wallet_name, parent=None):
        super().__init__(parent)
        self.session = SessionLocal()
        self.wallet_name = wallet_name
        self.btc_service = BTCService()
        
        self.setWindowTitle("Add BTC Transaction")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        
        # Form layout
        form = QFormLayout()
        
        # BTC Address
        self.address_input = QLineEdit()
        form.addRow("BTC Address:", self.address_input)
        
        # Transaction ID (optional)
        self.txid_input = QLineEdit()
        self.txid_input.setPlaceholderText("Optional - speeds up verification")
        form.addRow("Transaction ID:", self.txid_input)
        
        # Transaction Date
        self.date_input = QDateTimeEdit(QDateTime.currentDateTime())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd HH:mm")
        form.addRow("Transaction Date:", self.date_input)
        
        # Exchange selection
        self.exchange_combo = QComboBox()
        self.load_exchanges()
        form.addRow("Source Exchange:", self.exchange_combo)
        
        # Purchase price
        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText("Price per BTC in USD")
        form.addRow("Purchase Price ($):", self.price_input)
        
        # Memo field
        self.memo_input = QLineEdit()
        self.memo_input.setPlaceholderText("Optional note about this transaction")
        form.addRow("Memo:", self.memo_input)
        
        layout.addLayout(form)
        
        # Transaction details label
        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)
        
        # Progress section
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        
        self.progress_label = QLabel()
        self.progress_label.setWordWrap(True)
        self.progress_label.hide()
        
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_label)
        layout.addLayout(progress_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.scan_button = QPushButton("Scan Blockchain for TX")
        self.scan_button.clicked.connect(self.verify_transaction)
        
        self.abort_button = QPushButton("Abort Scan")
        self.abort_button.clicked.connect(self.abort_scan)
        self.abort_button.hide()
        
        self.save_button = QPushButton("Save Transaction")
        self.save_button.clicked.connect(self.save_transaction)
        self.save_button.setEnabled(False)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.scan_button)
        button_layout.addWidget(self.abort_button)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        self.tx_details = None
        self.current_worker = None
    
    def clean_address(self, address_text):
        """Clean and validate Bitcoin address"""
        # Clean the address thoroughly
        address = address_text.replace('\n', '').replace('\r', '').replace('\t', '').strip()
        
        if not address:
            raise ValueError("Please enter a BTC address")
        
        # Basic address validation
        if len(address) < 26 or len(address) > 62:
            raise ValueError("Bitcoin address length is invalid")
        
        # Check if address contains only valid characters
        import re
        if not re.match(r'^[a-zA-Z0-9]+$', address):
            raise ValueError("Bitcoin address contains invalid characters")
        
        return address
    
    def load_exchanges(self):
        exchanges = self.session.query(Exchange)\
            .filter(Exchange.active == True)\
            .order_by(Exchange.name)\
            .all()
        
        self.exchange_combo.clear()
        for exchange in exchanges:
            self.exchange_combo.addItem(exchange.name, exchange.id)
    
    def verify_transaction(self):
        try:
            # Clean and validate the address
            address = self.clean_address(self.address_input.text())
            
            # Update the input field with cleaned address
            self.address_input.setText(address)
            
            # Show progress indicators
            self.progress_bar.setRange(0, 0)
            self.progress_bar.show()
            self.progress_label.show()
            self.progress_label.setText("Starting verification...")
            
            # Disable scan button, show abort button
            self.scan_button.setEnabled(False)
            self.abort_button.show()
            
            # Start worker thread
            self.current_worker = ScanWorker(
                self.btc_service,
                address,
                self.date_input.dateTime().toPyDateTime(),
                self.txid_input.text().strip()  # Pass txid if provided
            )
            self.current_worker.progress.connect(self.update_progress)
            self.current_worker.finished.connect(self.scan_completed)
            self.current_worker.error.connect(self.scan_error)
            self.current_worker.start()
            
        except Exception as e:
            self.show_error(str(e))
    
    def abort_scan(self):
        if self.current_worker:
            self.current_worker.abort = True
            self.progress_label.setText("Aborting scan...")
    
    def update_progress(self, message):
        self.progress_label.setText(message)
    
    def scan_completed(self, result):
        self.tx_details = result
        self.cleanup_scan()
        
        # Update display with transaction details
        details_text = (
            f"Transaction found!\n"
            f"Amount: {result['amount']:.8f} BTC\n"
            f"Date: {result['date'].strftime('%Y-%m-%d %H:%M')}\n"
            f"Confirmations: {result['confirmations']}\n"
            f"Transaction ID: {result['txid']}"
        )
        self.details_label.setText(details_text)
        self.details_label.setStyleSheet("color: green;")
        self.save_button.setEnabled(True)
    
    def scan_error(self, error_message):
        self.cleanup_scan()
        self.show_error(error_message)
    
    def cleanup_scan(self):
        self.progress_bar.hide()
        self.progress_label.hide()
        self.abort_button.hide()
        self.scan_button.setEnabled(True)
        self.current_worker = None
    
    def show_error(self, message):
        self.details_label.setText(f"Error: {message}")
        self.details_label.setStyleSheet("color: red;")
        self.save_button.setEnabled(False)
    
    def save_transaction(self):
        try:
            if not self.tx_details:
                raise ValueError("Please verify the transaction first")
            
            price = float(self.price_input.text())
            if price <= 0:
                raise ValueError("Purchase price must be positive")
            
            # Clean the address before saving
            address = self.clean_address(self.address_input.text())
            
            # Get detailed block information using the transaction ID
            block_number = None
            block_time = None
            
            if self.btc_service.is_available and self.tx_details.get('txid'):
                try:
                    raw_tx_info = self.btc_service.get_raw_transaction_info(self.tx_details['txid'])
                    block_number = raw_tx_info.get('block_number')
                    block_time = raw_tx_info.get('block_time')
                    logger.info(f"Retrieved block info for {self.tx_details['txid']} - Number: {block_number}, Time: {block_time}")
                except Exception as e:
                    logger.warning(f"Could not get block info for {self.tx_details['txid']}: {e}")
            
            # Create transaction record
            transaction = Transaction(
                wallet_name=self.wallet_name,
                countervalue_ticker="USD",
                currency_ticker="BTC",
                operation_type=OperationType.IN,
                operation_date=self.tx_details['date'],
                operation_amount=self.tx_details['amount'],
                operation_fees=0.0,  # Fees not tracked for manual entries
                cost_basis=price,
                cost_basis_minus_fees=price,
                status="Confirmed" if self.tx_details['confirmations'] >= 6 else "Pending",
                account_name="Manual Entry",
                account_xpub=address,  # Use cleaned address
                countervalue_at_operation=price * self.tx_details['amount'],
                operation_hash=self.tx_details['txid'],
                available_to_spend=self.tx_details['amount'],
                memo=self.memo_input.text().strip() or None,
                block_number=block_number,  # Add block information
                block_time=block_time       # Add block time
            )
            
            self.session.add(transaction)
            self.session.commit()
            
            # Show success message with block information
            success_msg = f"Added BTC transaction for {self.tx_details['amount']:.8f} BTC"
            if block_number:
                success_msg += f"\nBlock: {block_number}"
                if block_time:
                    success_msg += f"\nBlock Time: {block_time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            QMessageBox.information(
                self,
                "Success",
                success_msg
            )
            self.accept()
            
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
        except Exception as e:
            self.session.rollback()
            QMessageBox.critical(self, "Error", f"Failed to save transaction: {str(e)}") 