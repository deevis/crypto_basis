"""
Split Transaction Dialog

Handles transactions where an existing UTXO is consumed and multiple new 
addresses receive outputs. Common scenarios:
- Sending BTC to multiple recipients
- Creating change outputs
- Splitting holdings across multiple wallets

Features:
- Detects if source address was monitored
- Prompts to monitor new destination addresses
- Allows wallet assignment per output
- Tracks cost basis from source UTXO
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QComboBox, QFormLayout, QMessageBox, QDateTimeEdit,
    QProgressBar, QTableWidget, QTableWidgetItem, QCheckBox, QGroupBox,
    QHeaderView, QWidget, QScrollArea
)
from PyQt6.QtCore import Qt, QDateTime, QThread, pyqtSignal
from db_config import SessionLocal
from models import (
    Transaction, OperationType, Exchange, BTCAddressMonitoring, 
    BTCAddressUTXO
)
from btc_service import BTCService
from sqlalchemy import func
from datetime import datetime
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class TxFetchWorker(QThread):
    """Worker thread to fetch transaction details from blockchain"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, btc_service, txid):
        super().__init__()
        self.btc_service = btc_service
        self.txid = txid
    
    def run(self):
        try:
            # Get raw transaction with full details
            tx_data = self.btc_service._call_rpc("getrawtransaction", [self.txid, True])
            
            if not tx_data:
                self.error.emit("Transaction not found")
                return
            
            # Get block info
            block_height = None
            block_time = None
            if 'blockhash' in tx_data:
                block_info = self.btc_service._call_rpc("getblock", [tx_data['blockhash']])
                block_height = block_info.get('height')
                block_time = datetime.fromtimestamp(block_info.get('time', 0))
            
            # Process inputs - get source addresses and amounts
            inputs = []
            total_input = Decimal('0')
            
            for vin in tx_data.get('vin', []):
                if 'coinbase' in vin:
                    inputs.append({
                        'txid': 'coinbase',
                        'vout': 0,
                        'address': 'Coinbase (Mining Reward)',
                        'amount': Decimal('0')  # Will be calculated from outputs
                    })
                else:
                    # Fetch the previous transaction to get input details
                    prev_txid = vin.get('txid')
                    prev_vout = vin.get('vout')
                    
                    if prev_txid:
                        try:
                            prev_tx = self.btc_service._call_rpc("getrawtransaction", [prev_txid, True])
                            prev_output = prev_tx['vout'][prev_vout]
                            
                            # Get address
                            script = prev_output.get('scriptPubKey', {})
                            address = script.get('address') or (script.get('addresses', [None])[0])
                            amount = Decimal(str(prev_output.get('value', 0)))
                            
                            inputs.append({
                                'txid': prev_txid,
                                'vout': prev_vout,
                                'address': address or 'Unknown',
                                'amount': amount
                            })
                            total_input += amount
                        except Exception as e:
                            logger.warning(f"Could not fetch input {prev_txid}:{prev_vout}: {e}")
                            inputs.append({
                                'txid': prev_txid,
                                'vout': prev_vout,
                                'address': 'Unknown',
                                'amount': Decimal('0')
                            })
            
            # Process outputs
            outputs = []
            total_output = Decimal('0')
            
            for i, vout in enumerate(tx_data.get('vout', [])):
                script = vout.get('scriptPubKey', {})
                address = script.get('address') or (script.get('addresses', [None])[0])
                amount = Decimal(str(vout.get('value', 0)))
                
                # Check script type
                script_type = script.get('type', 'unknown')
                
                outputs.append({
                    'vout': i,
                    'address': address or f'Non-standard ({script_type})',
                    'amount': amount,
                    'script_type': script_type
                })
                total_output += amount
            
            # Calculate fee
            fee = total_input - total_output if total_input > 0 else Decimal('0')
            
            result = {
                'txid': self.txid,
                'block_height': block_height,
                'block_time': block_time,
                'inputs': inputs,
                'outputs': outputs,
                'total_input': total_input,
                'total_output': total_output,
                'fee': fee,
                'confirmations': tx_data.get('confirmations', 0)
            }
            
            self.finished.emit(result)
            
        except Exception as e:
            self.error.emit(str(e))


class SplitTransactionDialog(QDialog):
    """Dialog for handling transactions with multiple outputs"""
    
    def __init__(self, parent=None, txid=None):
        super().__init__(parent)
        self.session = SessionLocal()
        self.btc_service = BTCService(test_connection=True)
        self.tx_data = None
        self.output_widgets = []  # Store output row widgets
        
        self.setWindowTitle("Split Transaction / Multi-Output Transaction")
        self.setModal(True)
        self.setMinimumSize(800, 600)
        
        self.setup_ui()
        
        # If txid provided, auto-fetch
        if txid:
            self.txid_input.setText(txid)
            self.fetch_transaction()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Transaction ID input
        txid_layout = QHBoxLayout()
        txid_layout.addWidget(QLabel("Transaction ID:"))
        self.txid_input = QLineEdit()
        self.txid_input.setPlaceholderText("Enter the Bitcoin transaction ID")
        txid_layout.addWidget(self.txid_input)
        
        self.fetch_button = QPushButton("Fetch Transaction")
        self.fetch_button.clicked.connect(self.fetch_transaction)
        txid_layout.addWidget(self.fetch_button)
        
        layout.addLayout(txid_layout)
        
        # Progress indicator
        self.progress_label = QLabel()
        self.progress_label.hide()
        layout.addWidget(self.progress_label)
        
        # Transaction summary
        self.summary_group = QGroupBox("Transaction Summary")
        self.summary_group.hide()
        summary_layout = QFormLayout(self.summary_group)
        
        self.block_label = QLabel()
        summary_layout.addRow("Block:", self.block_label)
        
        self.time_label = QLabel()
        summary_layout.addRow("Time:", self.time_label)
        
        self.fee_label = QLabel()
        summary_layout.addRow("Fee:", self.fee_label)
        
        self.confirmations_label = QLabel()
        summary_layout.addRow("Confirmations:", self.confirmations_label)
        
        layout.addWidget(self.summary_group)
        
        # Inputs section
        self.inputs_group = QGroupBox("Inputs (Source UTXOs)")
        self.inputs_group.hide()
        inputs_layout = QVBoxLayout(self.inputs_group)
        
        self.inputs_table = QTableWidget()
        self.inputs_table.setColumnCount(4)
        self.inputs_table.setHorizontalHeaderLabels(["Address", "Amount (BTC)", "Was Monitored", "Had Transaction"])
        self.inputs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        inputs_layout.addWidget(self.inputs_table)
        
        layout.addWidget(self.inputs_group)
        
        # Outputs section
        self.outputs_group = QGroupBox("Outputs (Destination Addresses)")
        self.outputs_group.hide()
        outputs_layout = QVBoxLayout(self.outputs_group)
        
        # Instructions
        outputs_layout.addWidget(QLabel(
            "Check 'Mine' for addresses you own. Assign wallets and optionally enable monitoring."
        ))
        
        self.outputs_table = QTableWidget()
        self.outputs_table.setColumnCount(6)
        self.outputs_table.setHorizontalHeaderLabels([
            "Mine", "Address", "Amount (BTC)", "Wallet", "Monitor", "Notes"
        ])
        self.outputs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        outputs_layout.addWidget(self.outputs_table)
        
        layout.addWidget(self.outputs_group)
        
        # Cost basis section
        self.cost_basis_group = QGroupBox("Cost Basis")
        self.cost_basis_group.hide()
        cost_layout = QFormLayout(self.cost_basis_group)
        
        self.source_cost_label = QLabel("Will be calculated from source transactions")
        cost_layout.addRow("Source Cost Basis:", self.source_cost_label)
        
        self.override_cost_check = QCheckBox("Override with manual cost basis")
        self.override_cost_check.stateChanged.connect(self.toggle_cost_override)
        cost_layout.addRow(self.override_cost_check)
        
        self.manual_cost_input = QLineEdit()
        self.manual_cost_input.setPlaceholderText("Total cost basis in USD")
        self.manual_cost_input.setEnabled(False)
        cost_layout.addRow("Manual Cost Basis ($):", self.manual_cost_input)
        
        layout.addWidget(self.cost_basis_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_button = QPushButton("Save Transactions")
        self.save_button.clicked.connect(self.save_transactions)
        self.save_button.setEnabled(False)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
    
    def toggle_cost_override(self, state):
        self.manual_cost_input.setEnabled(state == Qt.CheckState.Checked.value)
    
    def on_wallet_changed(self, combo, row):
        """Handle wallet combo box changes - create new wallet if requested"""
        if combo.currentData() == "__NEW__":
            # Prompt for new wallet name
            from PyQt6.QtWidgets import QInputDialog
            
            wallet_name, ok = QInputDialog.getText(
                self,
                "Create New Wallet",
                "Enter name for new wallet:",
                QLineEdit.EchoMode.Normal
            )
            
            if ok and wallet_name.strip():
                wallet_name = wallet_name.strip()
                
                # Check if wallet already exists
                existing_idx = combo.findText(wallet_name)
                if existing_idx >= 0:
                    combo.setCurrentIndex(existing_idx)
                    return
                
                # Add to this combo box (after "Create New" option)
                combo.insertItem(2, wallet_name, wallet_name)
                combo.setCurrentIndex(2)
                
                # Add to all other wallet combos too for consistency
                for widget_data in self.output_widgets:
                    other_combo = widget_data.get('wallet_combo')
                    if other_combo and other_combo != combo:
                        # Check if already added
                        if other_combo.findText(wallet_name) < 0:
                            other_combo.insertItem(2, wallet_name, wallet_name)
                
                logger.info(f"Created new wallet option: {wallet_name}")
            else:
                # User cancelled - reset to "Select Wallet"
                combo.setCurrentIndex(0)
    
    def fetch_transaction(self):
        txid = self.txid_input.text().strip()
        if not txid:
            QMessageBox.warning(self, "Error", "Please enter a transaction ID")
            return
        
        if not self.btc_service.is_available:
            QMessageBox.critical(self, "Error", "Bitcoin Core RPC is not available")
            return
        
        # Show progress
        self.progress_label.setText("Fetching transaction details...")
        self.progress_label.show()
        self.fetch_button.setEnabled(False)
        
        # Start worker
        self.worker = TxFetchWorker(self.btc_service, txid)
        self.worker.finished.connect(self.on_tx_fetched)
        self.worker.error.connect(self.on_fetch_error)
        self.worker.start()
    
    def on_fetch_error(self, error):
        self.progress_label.hide()
        self.fetch_button.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to fetch transaction: {error}")
    
    def on_tx_fetched(self, tx_data):
        self.progress_label.hide()
        self.fetch_button.setEnabled(True)
        self.tx_data = tx_data
        
        # Show summary
        self.summary_group.show()
        self.block_label.setText(str(tx_data.get('block_height', 'Unconfirmed')))
        
        block_time = tx_data.get('block_time')
        self.time_label.setText(block_time.strftime('%Y-%m-%d %H:%M:%S') if block_time else 'Unknown')
        
        fee = tx_data.get('fee', Decimal('0'))
        self.fee_label.setText(f"{float(fee):.8f} BTC")
        
        self.confirmations_label.setText(str(tx_data.get('confirmations', 0)))
        
        # Populate inputs
        self.populate_inputs(tx_data['inputs'])
        
        # Populate outputs
        self.populate_outputs(tx_data['outputs'])
        
        # Calculate source cost basis
        self.calculate_source_cost_basis(tx_data['inputs'])
        
        # Enable save
        self.save_button.setEnabled(True)
    
    def populate_inputs(self, inputs):
        self.inputs_group.show()
        self.inputs_table.setRowCount(len(inputs))
        
        for i, inp in enumerate(inputs):
            address = inp.get('address', 'Unknown')
            amount = inp.get('amount', Decimal('0'))
            
            # Check if this address was monitored
            monitoring = self.session.query(BTCAddressMonitoring).filter(
                BTCAddressMonitoring.bitcoin_address == address
            ).first()
            
            # Check if we have transactions for this address
            tx_count = self.session.query(Transaction).filter(
                Transaction.account_xpub == address,
                Transaction.currency_ticker == 'BTC'
            ).count()
            
            # Address
            addr_item = QTableWidgetItem(address)
            if monitoring:
                addr_item.setBackground(Qt.GlobalColor.lightGray)
            self.inputs_table.setItem(i, 0, addr_item)
            
            # Amount
            self.inputs_table.setItem(i, 1, QTableWidgetItem(f"{float(amount):.8f}"))
            
            # Was monitored
            monitored_text = "Yes ✓" if monitoring else "No"
            monitored_item = QTableWidgetItem(monitored_text)
            if monitoring:
                monitored_item.setForeground(Qt.GlobalColor.darkGreen)
            self.inputs_table.setItem(i, 2, monitored_item)
            
            # Had transactions
            tx_text = f"Yes ({tx_count})" if tx_count > 0 else "No"
            self.inputs_table.setItem(i, 3, QTableWidgetItem(tx_text))
    
    def populate_outputs(self, outputs):
        self.outputs_group.show()
        self.outputs_table.setRowCount(len(outputs))
        self.output_widgets = []
        
        # Check which input addresses were monitored (for prompting)
        monitored_inputs = []
        for inp in self.tx_data.get('inputs', []):
            address = inp.get('address')
            if address:
                monitoring = self.session.query(BTCAddressMonitoring).filter(
                    BTCAddressMonitoring.bitcoin_address == address
                ).first()
                if monitoring:
                    monitored_inputs.append(monitoring)
        
        # Load wallets for combo box
        wallets = self.session.query(Transaction.wallet_name).distinct().all()
        wallet_names = [w[0] for w in wallets]
        
        for i, out in enumerate(outputs):
            address = out.get('address', 'Unknown')
            amount = out.get('amount', Decimal('0'))
            
            # Check if already monitored or has transactions
            existing_monitoring = self.session.query(BTCAddressMonitoring).filter(
                BTCAddressMonitoring.bitcoin_address == address
            ).first()
            
            existing_tx = self.session.query(Transaction).filter(
                Transaction.account_xpub == address,
                Transaction.currency_ticker == 'BTC'
            ).first()
            
            # "Mine" checkbox
            mine_check = QCheckBox()
            # Pre-check if we already have this address
            if existing_monitoring or existing_tx:
                mine_check.setChecked(True)
            mine_widget = QWidget()
            mine_layout = QHBoxLayout(mine_widget)
            mine_layout.addWidget(mine_check)
            mine_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mine_layout.setContentsMargins(0, 0, 0, 0)
            self.outputs_table.setCellWidget(i, 0, mine_widget)
            
            # Address
            addr_item = QTableWidgetItem(address)
            if existing_monitoring:
                addr_item.setBackground(Qt.GlobalColor.lightGray)
            self.outputs_table.setItem(i, 1, addr_item)
            
            # Amount
            self.outputs_table.setItem(i, 2, QTableWidgetItem(f"{float(amount):.8f}"))
            
            # Wallet combo with "Create New" option
            wallet_combo = QComboBox()
            wallet_combo.addItem("-- Select Wallet --", None)
            wallet_combo.addItem("➕ Create New Wallet...", "__NEW__")
            for wallet in wallet_names:
                wallet_combo.addItem(wallet, wallet)
            
            # Pre-select wallet if we have existing transaction
            if existing_tx:
                idx = wallet_combo.findText(existing_tx.wallet_name)
                if idx >= 0:
                    wallet_combo.setCurrentIndex(idx)
            
            # Connect to handle "Create New" selection
            wallet_combo.currentIndexChanged.connect(
                lambda idx, combo=wallet_combo, row=i: self.on_wallet_changed(combo, row)
            )
            
            self.outputs_table.setCellWidget(i, 3, wallet_combo)
            
            # Monitor checkbox - pre-check if source was monitored
            monitor_check = QCheckBox()
            if monitored_inputs and not existing_monitoring:
                monitor_check.setChecked(True)  # Suggest monitoring if source was monitored
            elif existing_monitoring:
                monitor_check.setChecked(True)
                monitor_check.setEnabled(False)  # Already monitored
            
            monitor_widget = QWidget()
            monitor_layout = QHBoxLayout(monitor_widget)
            monitor_layout.addWidget(monitor_check)
            monitor_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            monitor_layout.setContentsMargins(0, 0, 0, 0)
            self.outputs_table.setCellWidget(i, 4, monitor_widget)
            
            # Notes
            notes = []
            if existing_monitoring:
                notes.append("Already monitored")
            if existing_tx:
                notes.append(f"Existing tx in {existing_tx.wallet_name}")
            if out.get('script_type') == 'nulldata':
                notes.append("OP_RETURN (data)")
            
            self.outputs_table.setItem(i, 5, QTableWidgetItem(", ".join(notes) if notes else ""))
            
            # Store widgets for later access
            self.output_widgets.append({
                'address': address,
                'amount': amount,
                'mine_check': mine_check,
                'wallet_combo': wallet_combo,
                'monitor_check': monitor_check,
                'vout': out.get('vout'),
                'existing_monitoring': existing_monitoring,
                'existing_tx': existing_tx
            })
        
        # Show prompt if source was monitored
        if monitored_inputs:
            source_labels = [m.source_label for m in monitored_inputs]
            QMessageBox.information(
                self,
                "Monitored Source Detected",
                f"The source address(es) were being monitored:\n"
                f"• {chr(10).join(source_labels)}\n\n"
                f"New output addresses have been pre-selected for monitoring.\n"
                f"Please verify and assign wallets to addresses you own."
            )
    
    def calculate_source_cost_basis(self, inputs):
        """Calculate total cost basis from source transactions"""
        self.cost_basis_group.show()
        
        total_cost = Decimal('0')
        found_cost = False
        
        for inp in inputs:
            address = inp.get('address')
            if not address or address == 'Coinbase (Mining Reward)':
                continue
            
            # Find the source transaction in our database
            source_tx = self.session.query(Transaction).filter(
                Transaction.account_xpub == address,
                Transaction.currency_ticker == 'BTC',
                Transaction.operation_type == OperationType.IN
            ).first()
            
            if source_tx:
                # Calculate proportional cost basis
                cost_per_btc = Decimal(str(source_tx.cost_basis))
                input_amount = inp.get('amount', Decimal('0'))
                total_cost += cost_per_btc * input_amount
                found_cost = True
        
        if found_cost:
            self.source_cost_label.setText(f"${float(total_cost):,.2f} (from source transactions)")
            self.source_cost_label.setStyleSheet("color: green;")
        else:
            self.source_cost_label.setText("No source transactions found - please enter manually")
            self.source_cost_label.setStyleSheet("color: orange;")
            self.override_cost_check.setChecked(True)
    
    def save_transactions(self):
        """Save all selected output transactions and create balancing OUT transactions for inputs"""
        if not self.tx_data:
            QMessageBox.warning(self, "Error", "No transaction data loaded")
            return
        
        # Collect selected outputs
        outputs_to_save = []
        for widget_data in self.output_widgets:
            if not widget_data['mine_check'].isChecked():
                continue
            
            wallet = widget_data['wallet_combo'].currentData()
            if not wallet:
                QMessageBox.warning(
                    self, "Error",
                    f"Please select a wallet for address: {widget_data['address'][:20]}..."
                )
                return
            
            outputs_to_save.append({
                'address': widget_data['address'],
                'amount': widget_data['amount'],
                'wallet': wallet,
                'monitor': widget_data['monitor_check'].isChecked(),
                'vout': widget_data['vout'],
                'existing_monitoring': widget_data['existing_monitoring'],
                'existing_tx': widget_data['existing_tx']
            })
        
        if not outputs_to_save:
            QMessageBox.warning(self, "Error", "Please select at least one output address as yours")
            return
        
        # Calculate cost basis
        if self.override_cost_check.isChecked():
            try:
                total_cost = Decimal(self.manual_cost_input.text())
            except:
                QMessageBox.warning(self, "Error", "Please enter a valid cost basis amount")
                return
        else:
            # Get from source
            total_cost = self.get_source_cost_basis()
        
        # Calculate total amount being claimed
        total_amount = sum(o['amount'] for o in outputs_to_save)
        
        # Cost per BTC
        cost_per_btc = total_cost / total_amount if total_amount > 0 else Decimal('0')
        
        try:
            out_tx_count = 0
            in_tx_count = 0
            
            # FIRST: Create OUT transactions for consumed inputs (source UTXOs)
            for inp in self.tx_data.get('inputs', []):
                address = inp.get('address')
                amount = inp.get('amount', Decimal('0'))
                
                if not address or address == 'Coinbase (Mining Reward)' or address == 'Unknown':
                    continue
                
                # Find the source IN transaction in our database
                source_tx = self.session.query(Transaction).filter(
                    Transaction.account_xpub == address,
                    Transaction.currency_ticker == 'BTC',
                    Transaction.operation_type == OperationType.IN
                ).first()
                
                if not source_tx:
                    logger.info(f"No source transaction found for input {address}, skipping OUT creation")
                    continue
                
                # Check if OUT transaction already exists for this txid
                existing_out = self.session.query(Transaction).filter(
                    Transaction.account_xpub == address,
                    Transaction.currency_ticker == 'BTC',
                    Transaction.operation_type == OperationType.OUT,
                    Transaction.operation_hash == self.tx_data['txid']
                ).first()
                
                if existing_out:
                    logger.info(f"OUT transaction already exists for {address}")
                    continue
                
                # Create balancing OUT transaction
                out_transaction = Transaction(
                    wallet_name=source_tx.wallet_name,  # Same wallet as source
                    countervalue_ticker="USD",
                    currency_ticker="BTC",
                    operation_type=OperationType.OUT,
                    operation_date=self.tx_data.get('block_time') or datetime.now(),
                    operation_amount=float(amount),
                    operation_fees=float(self.tx_data.get('fee', Decimal('0'))),  # Assign fee to OUT
                    cost_basis=source_tx.cost_basis,  # Carry forward cost basis
                    cost_basis_minus_fees=source_tx.cost_basis_minus_fees,
                    status="Confirmed" if self.tx_data.get('confirmations', 0) >= 6 else "Pending",
                    account_name=source_tx.account_name,
                    account_xpub=address,
                    countervalue_at_operation=float(source_tx.cost_basis * float(amount)),
                    operation_hash=self.tx_data['txid'],
                    available_to_spend=0.0,  # Spent
                    memo=f"Spent in split transaction to {len(outputs_to_save)} outputs",
                    block_number=self.tx_data.get('block_height'),
                    block_time=self.tx_data.get('block_time')
                )
                self.session.add(out_transaction)
                out_tx_count += 1
                logger.info(f"Created OUT transaction for {address}: {float(amount):.8f} BTC")
                
                # Update the source transaction's available_to_spend to 0
                source_tx.available_to_spend = 0.0
                
                # Mark UTXO as spent if it exists in monitoring
                utxo = self.session.query(BTCAddressUTXO).filter(
                    BTCAddressUTXO.bitcoin_address == address,
                    BTCAddressUTXO.spent_in_tx.is_(None)
                ).first()
                
                if utxo:
                    utxo.spent_in_tx = self.tx_data['txid']
                    logger.info(f"Marked UTXO as spent: {utxo.txid}:{utxo.vout}")
            
            # SECOND: Save each output as an IN transaction
            for out in outputs_to_save:
                # Skip if transaction already exists
                if out['existing_tx']:
                    logger.info(f"Skipping existing transaction for {out['address']}")
                    continue
                
                # Create IN transaction
                transaction = Transaction(
                    wallet_name=out['wallet'],
                    countervalue_ticker="USD",
                    currency_ticker="BTC",
                    operation_type=OperationType.IN,
                    operation_date=self.tx_data.get('block_time') or datetime.now(),
                    operation_amount=float(out['amount']),
                    operation_fees=0.0,
                    cost_basis=float(cost_per_btc),
                    cost_basis_minus_fees=float(cost_per_btc),
                    status="Confirmed" if self.tx_data.get('confirmations', 0) >= 6 else "Pending",
                    account_name="Split Transaction",
                    account_xpub=out['address'],
                    countervalue_at_operation=float(cost_per_btc * out['amount']),
                    operation_hash=f"{self.tx_data['txid']}:{out['vout']}",  # Include vout to allow multiple outputs per wallet
                    available_to_spend=float(out['amount']),
                    memo=f"Output {out['vout']} of split transaction",
                    block_number=self.tx_data.get('block_height'),
                    block_time=self.tx_data.get('block_time')
                )
                self.session.add(transaction)
                in_tx_count += 1
                
                # Add monitoring if requested
                if out['monitor'] and not out['existing_monitoring']:
                    monitoring = BTCAddressMonitoring(
                        bitcoin_address=out['address'],
                        source_label=f"Split from tx {self.tx_data['txid'][:16]}...",
                        monitor_status='active',
                        origin_block_number=self.tx_data.get('block_height')
                    )
                    self.session.add(monitoring)
                    logger.info(f"Added monitoring for {out['address']}")
            
            self.session.commit()
            
            # Import new monitored addresses to Bitcoin Core watch wallet
            addresses_to_import = [
                (o['address'], self.tx_data.get('block_height'))
                for o in outputs_to_save 
                if o['monitor'] and not o['existing_monitoring']
            ]
            
            import_success = 0
            import_failed = 0
            if addresses_to_import and self.btc_service.is_available:
                try:
                    self.btc_service.load_watch_wallet()
                    
                    for address, block_height in addresses_to_import:
                        try:
                            # Get timestamp from block
                            start_timestamp = None
                            if block_height:
                                block_hash = self.btc_service._call_rpc("getblockhash", [block_height])
                                block_info = self.btc_service._call_rpc("getblockheader", [block_hash])
                                start_timestamp = block_info.get('time')
                            
                            if not start_timestamp:
                                from datetime import timedelta
                                one_month_ago = datetime.now() - timedelta(days=30)
                                start_timestamp = int(one_month_ago.timestamp())
                            
                            # Import to Bitcoin Core
                            import_request = [{
                                "scriptPubKey": {"address": address},
                                "timestamp": start_timestamp,
                                "watchonly": True,
                                "label": f"monitored-{address[:8]}",
                                "rescan": False  # Don't rescan each one individually
                            }]
                            
                            result = self.btc_service._call_rpc("importmulti", [import_request, {"rescan": False}])
                            
                            if result and len(result) > 0 and result[0].get('success'):
                                import_success += 1
                                logger.info(f"Imported {address} to Bitcoin Core")
                            else:
                                # Try fallback
                                self.btc_service._call_rpc("importaddress", [address, f"monitored-{address[:8]}", False])
                                import_success += 1
                                logger.info(f"Imported {address} via fallback")
                        except Exception as e:
                            import_failed += 1
                            logger.warning(f"Failed to import {address}: {e}")
                    
                    # Trigger a rescan from the block height if we imported any
                    if import_success > 0 and self.tx_data.get('block_height'):
                        logger.info(f"Addresses imported. You may need to rescan from block {self.tx_data.get('block_height')}")
                        
                except Exception as e:
                    logger.error(f"Error importing addresses to Bitcoin Core: {e}")
            
            # Success message
            msg = f"Successfully processed split transaction:\n"
            msg += f"• {out_tx_count} OUT transaction(s) created (source UTXOs consumed)\n"
            msg += f"• {in_tx_count} IN transaction(s) created (new outputs)"
            
            monitored_count = sum(1 for o in outputs_to_save if o['monitor'] and not o['existing_monitoring'])
            if monitored_count > 0:
                msg += f"\n• {monitored_count} new address(es) added to monitoring"
                if import_success > 0:
                    msg += f"\n• {import_success} address(es) imported to Bitcoin Core"
                if import_failed > 0:
                    msg += f"\n• ⚠️ {import_failed} address(es) failed to import"
            
            QMessageBox.information(self, "Success", msg)
            self.accept()
            
        except Exception as e:
            self.session.rollback()
            logger.exception("Error saving split transaction")
            QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")
    
    def get_source_cost_basis(self):
        """Get cost basis from source transactions"""
        total_cost = Decimal('0')
        
        for inp in self.tx_data.get('inputs', []):
            address = inp.get('address')
            if not address or address == 'Coinbase (Mining Reward)':
                continue
            
            source_tx = self.session.query(Transaction).filter(
                Transaction.account_xpub == address,
                Transaction.currency_ticker == 'BTC',
                Transaction.operation_type == OperationType.IN
            ).first()
            
            if source_tx:
                cost_per_btc = Decimal(str(source_tx.cost_basis))
                input_amount = inp.get('amount', Decimal('0'))
                total_cost += cost_per_btc * input_amount
        
        return total_cost
    
    def closeEvent(self, event):
        self.session.close()
        super().closeEvent(event)
