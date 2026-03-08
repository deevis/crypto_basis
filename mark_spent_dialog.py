"""
Mark UTXO as Spent Dialog

Allows retroactively marking an IN transaction's UTXO as spent by providing
the spending transaction ID. Creates a balancing OUT transaction.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QFormLayout, QMessageBox, QGroupBox, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from db_config import SessionLocal
from models import Transaction, OperationType, BTCAddressUTXO, BTCAddressMonitoring, TransactionFulfillment
from btc_service import BTCService
from datetime import datetime
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class TxVerifyWorker(QThread):
    """Worker to verify the spending transaction"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, btc_service, txid, source_address):
        super().__init__()
        self.btc_service = btc_service
        self.txid = txid
        self.source_address = source_address
    
    def run(self):
        try:
            tx_data = self.btc_service._call_rpc("getrawtransaction", [self.txid, True])
            
            if not tx_data:
                self.error.emit("Transaction not found")
                return
            
            # Verify that the source address is in the inputs
            found_input = False
            input_amount = Decimal('0')
            
            for vin in tx_data.get('vin', []):
                if 'coinbase' in vin:
                    continue
                
                prev_txid = vin.get('txid')
                prev_vout = vin.get('vout')
                
                if prev_txid:
                    try:
                        prev_tx = self.btc_service._call_rpc("getrawtransaction", [prev_txid, True])
                        prev_output = prev_tx['vout'][prev_vout]
                        
                        script = prev_output.get('scriptPubKey', {})
                        address = script.get('address') or (script.get('addresses', [None])[0])
                        
                        if address == self.source_address:
                            found_input = True
                            input_amount = Decimal(str(prev_output.get('value', 0)))
                            break
                    except Exception as e:
                        logger.warning(f"Could not verify input: {e}")
            
            # Get block info
            block_height = None
            block_time = None
            if 'blockhash' in tx_data:
                block_info = self.btc_service._call_rpc("getblock", [tx_data['blockhash']])
                block_height = block_info.get('height')
                block_time = datetime.fromtimestamp(block_info.get('time', 0))
            
            # Get fee
            total_input = Decimal('0')
            total_output = Decimal('0')
            
            for vin in tx_data.get('vin', []):
                if 'coinbase' not in vin:
                    try:
                        prev_tx = self.btc_service._call_rpc("getrawtransaction", [vin.get('txid'), True])
                        total_input += Decimal(str(prev_tx['vout'][vin.get('vout')].get('value', 0)))
                    except:
                        pass
            
            for vout in tx_data.get('vout', []):
                total_output += Decimal(str(vout.get('value', 0)))
            
            fee = total_input - total_output if total_input > 0 else Decimal('0')
            
            result = {
                'txid': self.txid,
                'found_input': found_input,
                'input_amount': input_amount,
                'block_height': block_height,
                'block_time': block_time,
                'confirmations': tx_data.get('confirmations', 0),
                'fee': fee,
                'output_count': len(tx_data.get('vout', []))
            }
            
            self.finished.emit(result)
            
        except Exception as e:
            self.error.emit(str(e))


class MarkSpentDialog(QDialog):
    """Dialog to mark an IN transaction as spent"""
    
    def __init__(self, transaction, parent=None):
        super().__init__(parent)
        self.session = SessionLocal()
        self.transaction = self.session.merge(transaction)
        self.btc_service = BTCService(test_connection=True)
        self.tx_info = None
        
        self.setWindowTitle("Mark UTXO as Spent")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Source transaction info
        source_group = QGroupBox("Source UTXO (IN Transaction)")
        source_layout = QFormLayout(source_group)
        
        source_layout.addRow("Wallet:", QLabel(self.transaction.wallet_name))
        source_layout.addRow("Address:", QLabel(self.transaction.account_xpub))
        source_layout.addRow("Amount:", QLabel(f"{self.transaction.operation_amount:.8f} BTC"))
        source_layout.addRow("Date:", QLabel(self.transaction.operation_date.strftime('%Y-%m-%d %H:%M')))
        source_layout.addRow("Cost Basis:", QLabel(f"${self.transaction.cost_basis:,.2f}/BTC"))
        source_layout.addRow("Available:", QLabel(f"{self.transaction.available_to_spend:.8f} BTC"))
        
        if self.transaction.operation_hash:
            source_layout.addRow("TX ID:", QLabel(self.transaction.operation_hash[:32] + "..."))
        
        layout.addWidget(source_group)
        
        # Spending transaction input
        spend_group = QGroupBox("Spending Transaction")
        spend_layout = QVBoxLayout(spend_group)
        
        form = QFormLayout()
        
        self.spend_txid_input = QLineEdit()
        self.spend_txid_input.setPlaceholderText("Enter the transaction ID that spent this UTXO")
        form.addRow("Spending TX ID:", self.spend_txid_input)
        
        spend_layout.addLayout(form)
        
        # Verify button
        verify_layout = QHBoxLayout()
        self.verify_button = QPushButton("Verify Transaction")
        self.verify_button.clicked.connect(self.verify_spending_tx)
        verify_layout.addWidget(self.verify_button)
        verify_layout.addStretch()
        spend_layout.addLayout(verify_layout)
        
        # Verification result
        self.verify_label = QLabel()
        self.verify_label.setWordWrap(True)
        spend_layout.addWidget(self.verify_label)
        
        layout.addWidget(spend_group)
        
        # Info about what will happen
        info_group = QGroupBox("What This Does")
        info_layout = QVBoxLayout(info_group)
        
        info_label = QLabel(
            "This will create a balancing OUT transaction to zero out the wallet balance.\n\n"
            "• The OUT transaction will consume the full UTXO amount\n"
            "• No new IN transactions will be created\n"
            "• Use this when you've already added the destination transactions separately"
        )
        info_label.setWordWrap(True)
        info_layout.addWidget(info_label)
        
        layout.addWidget(info_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_button = QPushButton("Mark as Spent")
        self.save_button.clicked.connect(self.save_spent)
        self.save_button.setEnabled(False)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
    
    def verify_spending_tx(self):
        txid = self.spend_txid_input.text().strip()
        
        if not txid:
            QMessageBox.warning(self, "Error", "Please enter a transaction ID")
            return
        
        if not self.btc_service.is_available:
            # Allow without verification
            reply = QMessageBox.question(
                self,
                "Bitcoin Core Unavailable",
                "Bitcoin Core is not available to verify the transaction.\n\n"
                "Do you want to proceed without verification?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.tx_info = {
                    'txid': txid,
                    'found_input': True,  # Assume true
                    'block_height': None,
                    'block_time': None,
                    'confirmations': 0,
                    'fee': Decimal('0')
                }
                self.verify_label.setText("⚠️ Transaction not verified (Bitcoin Core unavailable)")
                self.verify_label.setStyleSheet("color: orange;")
                self.save_button.setEnabled(True)
            return
        
        self.verify_button.setEnabled(False)
        self.verify_label.setText("Verifying transaction...")
        
        self.worker = TxVerifyWorker(
            self.btc_service, 
            txid, 
            self.transaction.account_xpub
        )
        self.worker.finished.connect(self.on_verify_complete)
        self.worker.error.connect(self.on_verify_error)
        self.worker.start()
    
    def on_verify_error(self, error):
        self.verify_button.setEnabled(True)
        self.verify_label.setText(f"❌ Error: {error}")
        self.verify_label.setStyleSheet("color: red;")
        self.save_button.setEnabled(False)
    
    def on_verify_complete(self, tx_info):
        self.verify_button.setEnabled(True)
        self.tx_info = tx_info
        
        if tx_info['found_input']:
            self.verify_label.setText(
                f"✅ Verified! Transaction spends this address.\n"
                f"Block: {tx_info.get('block_height', 'Unconfirmed')}\n"
                f"Time: {tx_info['block_time'].strftime('%Y-%m-%d %H:%M') if tx_info.get('block_time') else 'Unknown'}\n"
                f"Confirmations: {tx_info.get('confirmations', 0)}\n"
                f"Outputs: {tx_info.get('output_count', 0)}"
            )
            self.verify_label.setStyleSheet("color: green;")
            self.save_button.setEnabled(True)
            
            # If multiple outputs, suggest split transaction
            if tx_info.get('output_count', 0) > 1:
                self.verify_label.setText(
                    self.verify_label.text() + 
                    "\n\n💡 This transaction has multiple outputs. "
                    "Consider using 'Add Split Transaction' instead if some outputs are yours."
                )
        else:
            self.verify_label.setText(
                f"⚠️ Warning: Address {self.transaction.account_xpub[:20]}... "
                f"was NOT found in the inputs of this transaction.\n\n"
                f"Are you sure this is the correct spending transaction?"
            )
            self.verify_label.setStyleSheet("color: orange;")
            
            # Still allow saving with warning
            reply = QMessageBox.question(
                self,
                "Address Not Found",
                "The address was not found in the transaction inputs.\n\n"
                "Do you want to proceed anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.save_button.setEnabled(True)
    
    def save_spent(self):
        if not self.tx_info:
            QMessageBox.warning(self, "Error", "Please verify the spending transaction first")
            return
        
        try:
            spending_txid = self.tx_info['txid']
            
            # Check if OUT already exists
            existing_out = self.session.query(Transaction).filter(
                Transaction.account_xpub == self.transaction.account_xpub,
                Transaction.currency_ticker == 'BTC',
                Transaction.operation_type == OperationType.OUT,
                Transaction.operation_hash == spending_txid
            ).first()
            
            if existing_out:
                QMessageBox.warning(
                    self, 
                    "Already Exists",
                    "An OUT transaction for this spending TX already exists."
                )
                return
            
            # Create the OUT transaction
            out_transaction = Transaction(
                wallet_name=self.transaction.wallet_name,
                countervalue_ticker="USD",
                currency_ticker="BTC",
                operation_type=OperationType.OUT,
                operation_date=self.tx_info.get('block_time') or datetime.now(),
                operation_amount=self.transaction.operation_amount,  # Full amount
                operation_fees=float(self.tx_info.get('fee', Decimal('0'))),
                cost_basis=self.transaction.cost_basis,
                cost_basis_minus_fees=self.transaction.cost_basis_minus_fees,
                status="Confirmed" if self.tx_info.get('confirmations', 0) >= 6 else "Pending",
                account_name=self.transaction.account_name,
                account_xpub=self.transaction.account_xpub,
                countervalue_at_operation=self.transaction.cost_basis * self.transaction.operation_amount,
                operation_hash=spending_txid,
                available_to_spend=0.0,
                memo=f"Spent (retroactively marked)",
                block_number=self.tx_info.get('block_height'),
                block_time=self.tx_info.get('block_time')
            )
            self.session.add(out_transaction)
            
            # Flush to get the OUT transaction ID
            self.session.flush()
            
            # Create the fulfillment linking OUT to the source IN
            fulfillment = TransactionFulfillment(
                out_transaction_id=out_transaction.id,
                in_transaction_id=self.transaction.id,
                in_transaction_amount=float(self.transaction.operation_amount),
                in_transaction_cost_basis=float(self.transaction.cost_basis or 0),
                out_transaction_percent_filled=1.0  # 100% fulfilled
            )
            self.session.add(fulfillment)
            
            # Update the source IN transaction
            self.transaction.available_to_spend = 0.0
            
            # Mark UTXO as spent if it exists
            utxo = self.session.query(BTCAddressUTXO).filter(
                BTCAddressUTXO.bitcoin_address == self.transaction.account_xpub,
                BTCAddressUTXO.spent_in_tx.is_(None)
            ).first()
            
            if utxo:
                utxo.spent_in_tx = spending_txid
                logger.info(f"Marked UTXO as spent: {utxo.txid}:{utxo.vout}")
            
            self.session.commit()
            
            QMessageBox.information(
                self,
                "Success",
                f"Successfully marked UTXO as spent.\n\n"
                f"• Created OUT transaction for {self.transaction.operation_amount:.8f} BTC\n"
                f"• Created fulfillment link to source IN (cost basis: ${self.transaction.cost_basis:,.2f}/BTC)\n"
                f"• Updated available_to_spend to 0\n"
                f"• Spending TX: {spending_txid[:32]}..."
            )
            
            self.accept()
            
        except Exception as e:
            self.session.rollback()
            logger.exception("Error marking UTXO as spent")
            QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")
    
    def closeEvent(self, event):
        self.session.close()
        super().closeEvent(event)
