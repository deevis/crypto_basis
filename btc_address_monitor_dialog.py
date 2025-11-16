from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                           QTableWidget, QTableWidgetItem, QLabel, QComboBox,
                           QLineEdit, QMessageBox, QHeaderView, QMenu, QWidget,
                           QCheckBox, QGroupBox, QProgressDialog, QApplication)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QAction
from db_config import SessionLocal
from models import BTCAddressMonitoring, BTCAddressUTXO, Transaction
from decimal import Decimal
from datetime import datetime
import logging
import urllib.parse
import requests
from sqlalchemy.sql import func
from btc_service import BTCService

logger = logging.getLogger(__name__)

class BTCAddressMonitorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bitcoin Address Monitoring")
        self.setMinimumSize(900, 700)  # Made taller to accommodate new section
        
        self.setup_ui()
        self.load_addresses()
        self.check_unmonitored_addresses()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Add unmonitored addresses section
        unmonitored_group = QGroupBox("Unmonitored Transaction Addresses")
        unmonitored_group.setObjectName("unmonitored_group")
        unmonitored_layout = QVBoxLayout(unmonitored_group)
        
        # Add select all checkbox and monitor button
        select_layout = QHBoxLayout()
        self.select_all_check = QCheckBox("Select All")
        self.select_all_check.stateChanged.connect(self.toggle_all_selections)
        monitor_selected_btn = QPushButton("Monitor Selected")
        monitor_selected_btn.clicked.connect(self.monitor_selected_addresses)
        
        select_layout.addWidget(self.select_all_check)
        select_layout.addStretch()
        select_layout.addWidget(monitor_selected_btn)
        unmonitored_layout.addLayout(select_layout)
        
        # Add table for unmonitored addresses
        self.unmonitored_table = QTableWidget()
        self.setup_unmonitored_table()
        unmonitored_layout.addWidget(self.unmonitored_table)
        
        layout.addWidget(unmonitored_group)
        
        # Add separator
        separator = QLabel()
        separator.setStyleSheet("border-bottom: 1px solid #ccc; margin: 10px 0;")
        layout.addWidget(separator)
        
        # Add controls section
        controls_layout = QHBoxLayout()
        
        # Add address section
        add_layout = QHBoxLayout()
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Bitcoin Address")
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("Source Label")
        
        add_button = QPushButton("Add Address")
        add_button.clicked.connect(self.add_address)
        
        add_layout.addWidget(QLabel("Address:"))
        add_layout.addWidget(self.address_input)
        add_layout.addWidget(QLabel("Source:"))
        add_layout.addWidget(self.source_input)
        add_layout.addWidget(add_button)
        
        # Filter section
        filter_layout = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Active", "Paused", "Disabled"])
        self.status_filter.currentTextChanged.connect(self.load_addresses)
        
        filter_layout.addWidget(QLabel("Status:"))
        filter_layout.addWidget(self.status_filter)
        
        # Combine controls
        controls_layout.addLayout(add_layout)
        controls_layout.addStretch()
        controls_layout.addLayout(filter_layout)
        
        layout.addLayout(controls_layout)
        
        # Add table
        self.table = QTableWidget()
        self.setup_table()
        layout.addWidget(self.table)
        
        # Add buttons
        button_layout = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.load_addresses)
        update_all_button = QPushButton("Update All")
        update_all_button.clicked.connect(self.update_all_addresses)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        
        button_layout.addWidget(refresh_button)
        button_layout.addWidget(update_all_button)
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
    
    def setup_table(self):
        headers = ["Source", "Address", "Balance", "Last Check", "Last Block", 
                  "Last Activity", "Last Activity Date", "Status", "Actions"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        
        # Enable sorting
        self.table.setSortingEnabled(True)
        
        # Set column widths
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        # Enable context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
    
    def load_addresses(self):
        """Load monitored addresses into table"""
        db = SessionLocal()
        try:
            # Get current block number from Bitcoin Core
            btc_service = BTCService(test_connection=True)
            current_block = None
            if btc_service.is_available:
                try:
                    chain_info = btc_service._call_rpc("getblockchaininfo")
                    current_block = chain_info.get('blocks')
                except Exception as e:
                    logger.error(f"Error getting current block number: {e}")
                    current_block = None
            
            # Update header with current block number
            if current_block is not None:
                logger.info(f"Current block: {current_block}")
                self.table.setToolTip(f"Current block: {current_block}")
                self.table.setStatusTip(f"Current block: {current_block}")
                self.table.setWhatsThis(f"Current block: {current_block}")
                self.table.setProperty('current_block', current_block)
            else:
                self.table.setToolTip("")
                self.table.setStatusTip("")
                self.table.setWhatsThis("")
                self.table.setProperty('current_block', None)
            
            query = db.query(BTCAddressMonitoring)
            
            # Apply status filter
            status_filter = self.status_filter.currentText()
            if status_filter != "All":
                query = query.filter(BTCAddressMonitoring.monitor_status == status_filter.lower())
            
            addresses = query.all()
            
            # Pre-fetch block timestamps for efficiency
            block_timestamps = {}
            if btc_service.is_available:
                unique_blocks = set()
                for addr in addresses:
                    if addr.last_activity_block is not None:
                        unique_blocks.add(addr.last_activity_block)
                
                for block_num in unique_blocks:
                    try:
                        block_hash = btc_service._call_rpc("getblockhash", [block_num])
                        block_info = btc_service._call_rpc("getblockheader", [block_hash])
                        block_timestamps[block_num] = block_info.get('time')
                    except Exception as e:
                        logger.warning(f"Could not get timestamp for block {block_num}: {e}")
                        block_timestamps[block_num] = None
            
            self.table.setRowCount(len(addresses))
            
            for i, addr in enumerate(addresses):
                # Format last activity text
                last_activity_text = ""
                last_activity_date_text = ""
                has_activity = False
                
                if addr.last_activity_block is not None:
                    last_activity_text = f"Block {addr.last_activity_block}"
                    if addr.last_transaction_hash:
                        last_activity_text += f"\nTx: {addr.last_transaction_hash[:8]}..."
                    has_activity = True
                    
                    # Get the date of the last activity block from cache
                    block_timestamp = block_timestamps.get(addr.last_activity_block)
                    if block_timestamp:
                        activity_date = datetime.fromtimestamp(block_timestamp)
                        last_activity_date_text = activity_date.strftime('%Y-%m-%d %H:%M:%S')
                    elif btc_service.is_available:
                        last_activity_date_text = "Unknown"
                    else:
                        last_activity_date_text = "RPC Unavailable"
                else:
                    last_activity_text = "No activity detected"
                    last_activity_date_text = "Never"
                
                items = [
                    QTableWidgetItem(addr.source_label),
                    QTableWidgetItem(addr.bitcoin_address),
                    QTableWidgetItem(f"{addr.last_known_balance:.8f}" if addr.last_known_balance else "0.00000000"),
                    QTableWidgetItem(addr.last_check_timestamp.strftime('%Y-%m-%d %H:%M:%S') if addr.last_check_timestamp else "Never"),
                    QTableWidgetItem(str(addr.last_block_checked) if addr.last_block_checked else ""),
                    QTableWidgetItem(last_activity_text),
                    QTableWidgetItem(last_activity_date_text),
                    QTableWidgetItem(addr.monitor_status.title()),
                ]
                
                for col, item in enumerate(items):
                    self.table.setItem(i, col, item)
                    
                    # Apply special formatting
                    if has_activity:
                        # Light green background for addresses with activity
                        item.setBackground(Qt.GlobalColor.green)
                    else:
                        # Light gray background for addresses with no activity
                        item.setBackground(Qt.GlobalColor.lightGray)
                
                # Highlight in yellow if not checked in more than 5 blocks
                if current_block is not None and addr.last_block_checked is not None:
                    if current_block - addr.last_block_checked > 5:
                        for col in range(len(items)):
                            self.table.item(i, col).setBackground(Qt.GlobalColor.yellow)
                
                # Add action buttons
                action_widget = self.create_action_buttons(addr)
                self.table.setCellWidget(i, len(items), action_widget)
        
        finally:
            db.close()
    
    def create_action_buttons(self, address):
        """Create action buttons for an address row"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 2, 2, 2)
        
        # View UTXOs button
        utxo_btn = QPushButton("UTXOs")
        utxo_btn.clicked.connect(lambda: self.show_utxos(address))
        layout.addWidget(utxo_btn)
        
        # Toggle status button
        toggle_btn = QPushButton("Pause" if address.monitor_status == 'active' else "Resume")
        toggle_btn.clicked.connect(lambda: self.toggle_status(address))
        layout.addWidget(toggle_btn)
        
        return widget
    
    def update_all_addresses(self):
        """Update all addresses with current blockchain information"""
        # Get current block
        btc_service = BTCService(test_connection=True)
        if not btc_service.is_available:
            QMessageBox.critical(self, "Error", "Bitcoin Core RPC not available")
            return
        
        try:
            btc_service.load_watch_wallet()
        except Exception as e:
            error_text = str(e)
            if "is already loaded" not in error_text:
                QMessageBox.critical(self, "Error", f"Failed to load wallet: {str(e)}")
                return
        
        # Get current block number
        try:
            chain_info = btc_service._call_rpc("getblockchaininfo")
            current_block = chain_info.get('blocks')
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to get blockchain info: {str(e)}")
            return
        
        # Get all active addresses that need updating
        db = SessionLocal()
        try:
            addresses = db.query(BTCAddressMonitoring)\
                .filter(BTCAddressMonitoring.monitor_status == 'active')\
                .all()
            
            if not addresses:
                QMessageBox.information(self, "No Addresses", "No active addresses to update")
                return
            
            # Create progress dialog
            progress = QProgressDialog("Updating Bitcoin addresses...", "Cancel", 0, len(addresses), self)
            progress.setWindowTitle("Update Progress")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            
            # Function to update an address
            def update_address(address, index):
                try:
                    # Update progress dialog
                    progress.setLabelText(f"Updating address {index+1}/{len(addresses)}:\n{address.bitcoin_address}")
                    progress.setValue(index)
                    
                    # Process events to keep UI responsive
                    QApplication.processEvents()
                    
                    if progress.wasCanceled():
                        return False
                    
                    # Get transactions
                    received = btc_service._call_rpc("listreceivedbyaddress", [0, True, True])
                    
                    txids = []
                    # Filter the results to find our specific address
                    for addr_info in received:
                        if addr_info.get('address') == address.bitcoin_address:
                            txids = addr_info.get('txids', [])
                            break
                    
                    # Get UTXOs
                    utxos = btc_service._call_rpc("listunspent", [0, 9999999, [address.bitcoin_address]])
                    
                    # Update balance
                    balance = Decimal('0')
                    if utxos and len(utxos) > 0:
                        balance = Decimal(str(sum(utxo.get('amount', 0) for utxo in utxos)))
                    
                    # Update address in database
                    address.last_known_balance = balance
                    
                    # Update last activity
                    activity_detected = False
                    if txids:
                        most_recent_tx = None
                        most_recent_block = None
                        
                        # Find most recent transaction
                        for txid in txids:
                            try:
                                tx_info = btc_service.get_raw_transaction_info(txid)
                                block_num = tx_info.get('block_number')
                                
                                if block_num and (most_recent_block is None or block_num > most_recent_block):
                                    most_recent_block = block_num
                                    most_recent_tx = txid
                            except Exception:
                                pass
                        
                        if most_recent_tx:
                            # Check if this is a new transaction
                            if address.last_transaction_hash != most_recent_tx:
                                activity_detected = True
                            address.last_transaction_hash = most_recent_tx
                        
                        if most_recent_block:
                            # Check if this is a new block activity
                            if address.last_activity_block != most_recent_block:
                                activity_detected = True
                            address.last_activity_block = most_recent_block
                    
                    # Update last check time and block
                    address.last_check_timestamp = datetime.utcnow()
                    address.last_block_checked = current_block
                    
                    # Update progress dialog with activity info
                    status_text = f"Updating address {index+1}/{len(addresses)}:\n{address.bitcoin_address}"
                    if activity_detected:
                        status_text += f"\n✓ Activity detected! {len(txids)} transactions."
                    else:
                        status_text += f"\n{len(txids)} transactions, no new activity."
                    
                    progress.setLabelText(status_text)
                    QApplication.processEvents()
                    
                    # Small delay to show status
                    if activity_detected:
                        QTimer.singleShot(1000, lambda: None)
                        QApplication.processEvents()
                    
                    return True
                except Exception as e:
                    logger.error(f"Error updating address {address.bitcoin_address}: {e}")
                    progress.setLabelText(f"Error updating {address.bitcoin_address}:\n{str(e)}")
                    QApplication.processEvents()
                    QTimer.singleShot(2000, lambda: None)
                    QApplication.processEvents()
                    return False
            
            # Update each address
            updated_count = 0
            for i, addr in enumerate(addresses):
                if update_address(addr, i):
                    updated_count += 1
                
                if progress.wasCanceled():
                    break
            
            # Commit changes
            db.commit()
            
            # Complete progress
            progress.setValue(len(addresses))
            
            # Show completion message
            if not progress.wasCanceled():
                QMessageBox.information(
                    self, 
                    "Update Complete", 
                    f"Successfully updated {updated_count} of {len(addresses)} addresses."
                )
            
            # Refresh table
            self.load_addresses()
            
        except Exception as e:
            db.rollback()
            QMessageBox.critical(self, "Error", f"Failed to update addresses: {str(e)}")
        finally:
            db.close()
    
    def show_context_menu(self, position):
        """Show context menu for table row"""
        menu = QMenu()
        
        view_action = QAction("View UTXOs", self)
        edit_action = QAction("Edit", self)
        delete_action = QAction("Delete", self)
        
        menu.addAction(view_action)
        menu.addAction(edit_action)
        menu.addSeparator()
        menu.addAction(delete_action)
        
        # Get the address for the selected row
        row = self.table.rowAt(position.y())
        if row >= 0:
            address = self.table.item(row, 1).text()
            
            view_action.triggered.connect(lambda: self.show_utxos_for_address(address))
            edit_action.triggered.connect(lambda: self.edit_address(address))
            delete_action.triggered.connect(lambda: self.delete_address(address))
            
            menu.exec(self.table.viewport().mapToGlobal(position))
    
    def add_address(self):
        """Add a new address to monitor"""
        address = self.address_input.text().strip()
        source = self.source_input.text().strip()
        
        # Clean the address more thoroughly
        address = address.replace('\n', '').replace('\r', '').replace('\t', '').strip()
        
        if not address or not source:
            QMessageBox.warning(self, "Input Error", "Both address and source label are required.")
            return
        
        # Basic address validation
        if len(address) < 26 or len(address) > 62:
            QMessageBox.warning(self, "Invalid Address", "Bitcoin address length is invalid.")
            return
        
        # Check if address contains only valid characters
        import re
        if not re.match(r'^[a-zA-Z0-9]+$', address):
            QMessageBox.warning(self, "Invalid Address", "Bitcoin address contains invalid characters.")
            return
        
        logger.info(f"Adding address: '{address}' (length: {len(address)})")
        logger.info(f"Source: '{source}'")
        
        db = SessionLocal()
        try:
            # Check if address already exists
            existing = db.query(BTCAddressMonitoring)\
                .filter(BTCAddressMonitoring.bitcoin_address == address)\
                .first()
            
            if existing:
                QMessageBox.warning(self, "Duplicate", "This address is already being monitored.")
                return
            
            # Try to discover the origin block - check database first
            btc_service = BTCService()
            logger.info(f"Discovering origin block for address: {address}")
            origin_block = None
            
            # Method 1: Check existing transactions in database
            # Use TRIM to handle potential whitespace issues in stored addresses
            from sqlalchemy import func
            existing_tx = db.query(Transaction).filter(
                func.trim(Transaction.account_xpub) == address,
                Transaction.block_number.isnot(None)
            ).order_by(Transaction.block_number).first()
            
            logger.debug(f"Database query result: existing_tx = {existing_tx}")
            if existing_tx and existing_tx.block_number:
                origin_block = existing_tx.block_number
                logger.info(f"✅ Method 1: Found origin block {origin_block} from existing database transactions")
                logger.info(f"   Transaction: {existing_tx.operation_hash} on {existing_tx.operation_date}")
            else:
                logger.info("❌ Method 1: No existing transactions with block numbers found in database, checking UTXOs...")
                
                # Method 2: Use scantxoutset to find any current UTXOs
                if btc_service.is_available:
                    try:
                        logger.info("🔍 Method 2: Scanning UTXOs with scantxoutset...")
                        utxos = btc_service._call_rpc("scantxoutset", ["start", [f"addr({address})"]])
                        logger.debug(f"scantxoutset result: {utxos}")
                        
                        if utxos.get('success') and utxos.get('unspents'):
                            logger.info(f"Found {len(utxos['unspents'])} UTXOs")
                            # Get the earliest block from current UTXOs
                            for i, utxo in enumerate(utxos.get('unspents', [])):
                                logger.debug(f"UTXO {i+1}: {utxo}")
                                tx_info = btc_service.get_raw_transaction_info(utxo['txid'])
                                block_num = tx_info.get('block_number')
                                logger.debug(f"UTXO {i+1} block_number: {block_num}")
                                if block_num and (origin_block is None or block_num < origin_block):
                                    origin_block = block_num
                                    logger.info(f"   Updated origin_block to {origin_block} from UTXO {utxo['txid']}")
                            
                            if origin_block:
                                logger.info(f"✅ Method 2: Found origin block {origin_block} from UTXOs")
                            else:
                                logger.warning("❌ Method 2: UTXOs found but no valid block numbers")
                        else:
                            logger.info("❌ Method 2: No UTXOs found for address")
                    except Exception as e:
                        logger.warning(f"❌ Method 2: Error scanning UTXOs: {e}")
                else:
                    logger.warning("❌ Method 2: Bitcoin Core not available")
                
                # Method 3: If still no origin block, use recent timestamp instead of genesis
                if not origin_block:
                    logger.info("❌ Method 3: No origin block found, will use recent timestamp for import")
            
            logger.info(f"🎯 Final origin_block value: {origin_block}")
            
            # Add new monitoring entry
            logger.info(f"Creating BTCAddressMonitoring with origin_block_number: {origin_block}")
            monitoring = BTCAddressMonitoring(
                bitcoin_address=address,
                source_label=source,
                monitor_status='active',
                origin_block_number=origin_block
            )
            
            db.add(monitoring)
            db.commit()
            
            # Verify it was saved correctly
            saved_monitoring = db.query(BTCAddressMonitoring)\
                .filter(BTCAddressMonitoring.bitcoin_address == address)\
                .first()
            logger.info(f"Saved monitoring entry - origin_block_number: {saved_monitoring.origin_block_number if saved_monitoring else 'NOT FOUND'}")
            
            # Try to import address to Bitcoin Core
            import_success = False
            if btc_service.is_available:
                try:
                    # Load the watch wallet
                    btc_service.load_watch_wallet()
                    
                    # Import the address using importmulti for better control
                    if origin_block:
                        # Use origin block timestamp for precise scanning
                        try:
                            block_hash = btc_service._call_rpc("getblockhash", [origin_block])
                            block_info = btc_service._call_rpc("getblockheader", [block_hash])
                            start_timestamp = block_info.get('time')
                            logger.info(f"Using origin block {origin_block} timestamp: {start_timestamp}")
                        except Exception as e:
                            logger.warning(f"Couldn't get timestamp for origin block {origin_block}: {e}")
                            start_timestamp = None
                    else:
                        start_timestamp = None
                    
                    # If no origin block found, use recent timestamp (1 month ago) instead of genesis
                    if start_timestamp is None:
                        from datetime import datetime, timedelta
                        one_month_ago = datetime.now() - timedelta(days=30)
                        start_timestamp = int(one_month_ago.timestamp())
                        logger.info(f"No origin block available, using recent timestamp (1 month ago): {start_timestamp}")
                    
                    # Use importmulti for better error handling
                    import_request = [{
                        "scriptPubKey": {"address": address},
                        "timestamp": start_timestamp,
                        "watchonly": True,
                        "label": f"monitored-{address[:8]}",
                        "rescan": True
                    }]
                    
                    logger.debug(f"Address being imported: '{address}' (length: {len(address)})")
                    logger.debug(f"Address repr: {repr(address)}")
                    logger.debug(f"Sending importmulti request: {import_request}")
                    logger.debug(f"Start timestamp: {start_timestamp}")
                    
                    result = btc_service._call_rpc("importmulti", [import_request, {"rescan": True}])
                    logger.debug(f"importmulti result: {result}")
                    
                    if result and len(result) > 0 and result[0].get('success'):
                        import_success = True
                        logger.info(f"Successfully imported address {address} to Bitcoin Core")
                    else:
                        # Enhanced error reporting
                        if result and len(result) > 0:
                            error_info = result[0].get('error', {})
                            error_msg = error_info.get('message', 'Unknown error')
                            error_code = error_info.get('code', 'No code')
                            logger.error(f"Failed to import address {address}: {error_msg} (code: {error_code})")
                            logger.error(f"Full error details: {error_info}")
                        else:
                            logger.error(f"Failed to import address {address}: No result returned")
                            logger.error(f"Full result: {result}")
                        
                        # Try alternative approach with importaddress
                        logger.info(f"Trying importaddress as fallback for {address}")
                        try:
                            btc_service._call_rpc("importaddress", [address, f"monitored-{address[:8]}", False])
                            import_success = True
                            logger.info(f"Successfully imported address {address} using importaddress fallback")
                        except Exception as fallback_error:
                            logger.error(f"Fallback importaddress also failed: {fallback_error}")
                        
                except Exception as e:
                    logger.error(f"Error importing address {address} to Bitcoin Core: {e}")
            
            # Show import status to user
            if btc_service.is_available:
                if import_success:
                    QMessageBox.information(
                        self, 
                        "Success", 
                        f"Address added to monitoring and imported to Bitcoin Core.\n\n"
                        f"Address: {address}\n"
                        f"Source: {source}\n"
                        f"Origin Block: {origin_block if origin_block else 'Unknown'}\n\n"
                        f"Bitcoin Core will rescan for transactions in the background."
                    )
                else:
                    QMessageBox.warning(
                        self, 
                        "Partial Success", 
                        f"Address added to monitoring but failed to import to Bitcoin Core.\n\n"
                        f"Address: {address}\n"
                        f"Source: {source}\n\n"
                        f"You can import it manually using the import tools."
                    )
            else:
                QMessageBox.information(
                    self, 
                    "Success", 
                    f"Address added to monitoring.\n\n"
                    f"Address: {address}\n"
                    f"Source: {source}\n"
                    f"Origin Block: {origin_block if origin_block else 'Unknown'}\n\n"
                    f"Bitcoin Core is not available. Import the address manually later."
                )
            
            # Clear inputs and refresh
            self.address_input.clear()
            self.source_input.clear()
            self.load_addresses()
            
        except Exception as e:
            db.rollback()
            QMessageBox.critical(self, "Error", f"Failed to add address: {str(e)}")
        finally:
            db.close()
    
    def toggle_status(self, address):
        """Toggle monitoring status between active and paused"""
        db = SessionLocal()
        try:
            monitoring = db.query(BTCAddressMonitoring)\
                .filter(BTCAddressMonitoring.bitcoin_address == address.bitcoin_address)\
                .first()
            
            if monitoring:
                monitoring.monitor_status = 'paused' if monitoring.monitor_status == 'active' else 'active'
                db.commit()
                self.load_addresses()
        
        finally:
            db.close()
    
    def show_utxos(self, address):
        """Show UTXOs for an address"""
        from btc_utxo_dialog import BTCUTXODialog
        dialog = BTCUTXODialog(address.bitcoin_address, self)
        dialog.exec()
    
    def show_utxos_for_address(self, address):
        """Show UTXOs for an address string"""
        from btc_utxo_dialog import BTCUTXODialog
        dialog = BTCUTXODialog(address, self)
        dialog.exec()
    
    def edit_address(self, address):
        """Edit address monitoring settings"""
        # Placeholder for future implementation
        QMessageBox.information(self, "Not Implemented", "Edit functionality not yet implemented")
    
    def delete_address(self, address):
        """Delete a monitored address"""
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to stop monitoring this address?\n\n{address}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            db = SessionLocal()
            try:
                db.query(BTCAddressMonitoring)\
                    .filter(BTCAddressMonitoring.bitcoin_address == address)\
                    .delete()
                db.commit()
                self.load_addresses()
            finally:
                db.close()
    
    def setup_unmonitored_table(self):
        """Setup the table for unmonitored addresses"""
        headers = ["", "Address", "Wallet", "Type", "Amount", "Last Transaction Date", "Transaction Count"]
        self.unmonitored_table.setColumnCount(len(headers))
        self.unmonitored_table.setHorizontalHeaderLabels(headers)
        
        # Enable sorting
        self.unmonitored_table.setSortingEnabled(True)
        
        # Set column widths
        self.unmonitored_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.unmonitored_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    
    def check_unmonitored_addresses(self):
        """Find addresses from transactions that aren't being monitored"""
        db = SessionLocal()
        try:
            # Get all monitored addresses
            monitored_addresses = {addr.bitcoin_address for addr in db.query(BTCAddressMonitoring).all()}
            
            # Get all unique BTC transaction addresses
            all_btc_addresses = db.query(
                Transaction.account_xpub
            ).filter(
                Transaction.currency_ticker == 'BTC',
                Transaction.account_xpub.isnot(None)
            ).distinct().all()
            
            total_btc_addresses = len({addr[0] for addr in all_btc_addresses})
            
            # If all addresses are monitored, show success message and hide unmonitored section
            if len(monitored_addresses) >= total_btc_addresses:
                # Hide the entire unmonitored group box and its contents
                unmonitored_group = self.findChild(QGroupBox, "unmonitored_group")
                if unmonitored_group:
                    unmonitored_group.hide()
                
                # Hide the separator
                for i in range(self.layout().count()):
                    item = self.layout().itemAt(i)
                    if isinstance(item.widget(), QLabel) and item.widget().styleSheet().startswith("border-bottom"):
                        item.widget().hide()
                        break
                
                # Show success message
                success_label = QLabel(f"All {total_btc_addresses} BTC wallet addresses are currently monitored")
                success_label.setStyleSheet("""
                    color: #2e7d32;  /* Dark green */
                    background-color: #e8f5e9;  /* Light green background */
                    padding: 10px;
                    border-radius: 5px;
                    font-weight: bold;
                    margin: 10px 0;
                """)
                success_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                
                # Add the success label at the top
                self.layout().insertWidget(0, success_label)
                return
            
            # Temporarily disable sorting while updating
            self.unmonitored_table.setSortingEnabled(False)
            
            # Get unmonitored addresses with details
            unmonitored = db.query(
                Transaction.account_xpub.label('bitcoin_address'),
                Transaction.wallet_name,
                Transaction.operation_type,
                Transaction.operation_amount,
                func.max(Transaction.operation_date).label('latest_date'),
                func.count(Transaction.id).label('tx_count')
            ).filter(
                Transaction.currency_ticker == 'BTC',
                Transaction.account_xpub.isnot(None)
            ).group_by(
                Transaction.account_xpub,
                Transaction.wallet_name,
                Transaction.operation_type,
                Transaction.operation_amount
            ).order_by(
                func.max(Transaction.operation_date).desc()
            ).all()
            
            # Filter out monitored addresses
            unmonitored = [tx for tx in unmonitored if tx.bitcoin_address not in monitored_addresses]
            
            # Show/hide the unmonitored section based on whether there are unmonitored addresses
            self.unmonitored_table.parent().parent().setVisible(bool(unmonitored))
            
            if not unmonitored:
                return
            
            # Update table
            self.unmonitored_table.setRowCount(len(unmonitored))
            
            for i, tx in enumerate(unmonitored):
                # Add checkbox
                checkbox = QCheckBox()
                checkbox_widget = QWidget()
                checkbox_layout = QHBoxLayout(checkbox_widget)
                checkbox_layout.addWidget(checkbox)
                checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                
                self.unmonitored_table.setCellWidget(i, 0, checkbox_widget)
                
                # Add other columns with proper sorting
                self.unmonitored_table.setItem(i, 1, QTableWidgetItem(tx.bitcoin_address))
                self.unmonitored_table.setItem(i, 2, QTableWidgetItem(tx.wallet_name))
                
                # Operation type
                type_item = QTableWidgetItem(tx.operation_type.value)
                type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.unmonitored_table.setItem(i, 3, type_item)
                
                # Amount with proper sorting
                amount_item = QTableWidgetItem()
                amount_item.setData(Qt.ItemDataRole.DisplayRole, f"{tx.operation_amount:.8f}")
                amount_item.setData(Qt.ItemDataRole.UserRole, tx.operation_amount)
                amount_item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
                self.unmonitored_table.setItem(i, 4, amount_item)
                
                # Date item with proper sorting
                date_item = QTableWidgetItem()
                date_item.setData(Qt.ItemDataRole.DisplayRole, tx.latest_date.strftime('%Y-%m-%d %H:%M'))
                date_item.setData(Qt.ItemDataRole.UserRole, tx.latest_date)
                self.unmonitored_table.setItem(i, 5, date_item)
                
                # Count item with numeric sorting
                count_item = QTableWidgetItem()
                count_item.setData(Qt.ItemDataRole.DisplayRole, str(tx.tx_count))
                count_item.setData(Qt.ItemDataRole.UserRole, tx.tx_count)
                count_item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
                self.unmonitored_table.setItem(i, 6, count_item)
            
            # Re-enable sorting after update
            self.unmonitored_table.setSortingEnabled(True)
            
        finally:
            db.close()
    
    def toggle_all_selections(self, state):
        """Toggle all checkboxes in unmonitored table"""
        for row in range(self.unmonitored_table.rowCount()):
            checkbox_widget = self.unmonitored_table.cellWidget(row, 0)
            if checkbox_widget:
                # Get the checkbox from the layout
                checkbox_layout = checkbox_widget.layout()
                if checkbox_layout:
                    # Get the first widget in the layout (our checkbox)
                    checkbox = checkbox_layout.itemAt(0).widget()
                    if isinstance(checkbox, QCheckBox):
                        checkbox.setChecked(bool(state))
    
    def monitor_selected_addresses(self):
        """Add selected addresses to monitoring and import them to Bitcoin Core"""
        selected_addresses = []
        
        for row in range(self.unmonitored_table.rowCount()):
            checkbox_widget = self.unmonitored_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox_layout = checkbox_widget.layout()
                if checkbox_layout:
                    checkbox = checkbox_layout.itemAt(0).widget()
                    if isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                        address = self.unmonitored_table.item(row, 1).text()
                        wallet = self.unmonitored_table.item(row, 2).text()
                        selected_addresses.append((address, wallet))
        
        if not selected_addresses:
            QMessageBox.warning(self, "No Selection", "Please select addresses to monitor.")
            return
        
        # Check Bitcoin Core availability first
        btc_service = BTCService(test_connection=True)
        if not btc_service.is_available:
            reply = QMessageBox.question(
                self,
                "Bitcoin Core Unavailable",
                "Bitcoin Core RPC is not available. Do you want to add addresses to monitoring without importing them to the wallet?\n\n"
                "You can import them later using the import tools.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            btc_service = None
        
        # Create progress dialog for the entire operation
        total_steps = len(selected_addresses) * 2  # Database + Import steps
        progress = QProgressDialog("Adding addresses to monitoring...", "Cancel", 0, total_steps, self)
        progress.setWindowTitle("Adding Addresses")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        db = SessionLocal()
        added_addresses = []
        
        try:
            # Step 1: Add addresses to database
            progress.setLabelText("Adding addresses to database...")
            QApplication.processEvents()
            
            for i, (address, wallet) in enumerate(selected_addresses):
                if progress.wasCanceled():
                    break
                
                progress.setLabelText(f"Adding to database ({i+1}/{len(selected_addresses)}):\n{address}")
                progress.setValue(i)
                QApplication.processEvents()
                
                # Find the earliest block for this address using improved logic
                logger.info(f"Discovering origin block for address: {address}")
                
                # Use TRIM to handle potential whitespace issues in stored addresses
                from sqlalchemy import func
                first_tx = db.query(Transaction).filter(
                    func.trim(Transaction.account_xpub) == address,
                    Transaction.block_number.isnot(None)
                ).order_by(
                    Transaction.block_number
                ).first()
                
                origin_block = None
                if first_tx and first_tx.block_number:
                    origin_block = first_tx.block_number
                    logger.info(f"✅ Found origin block {origin_block} from database transaction: {first_tx.operation_hash}")
                else:
                    logger.info(f"❌ No transactions with block numbers found for address {address}")
                
                logger.info(f"🎯 Origin block for {address}: {origin_block}")
                
                logger.info(f"Creating BTCAddressMonitoring for {address} with origin_block_number: {origin_block}")
                monitoring = BTCAddressMonitoring(
                    bitcoin_address=address,
                    source_label=f"From wallet: {wallet}",
                    monitor_status='active',
                    origin_block_number=origin_block
                )
                db.add(monitoring)
                added_addresses.append((address, origin_block))
            
            if not progress.wasCanceled():
                db.commit()
                logger.info(f"Added {len(added_addresses)} addresses to database")
                
                # Verify they were saved correctly
                for address, expected_origin_block in added_addresses:
                    saved_monitoring = db.query(BTCAddressMonitoring)\
                        .filter(BTCAddressMonitoring.bitcoin_address == address)\
                        .first()
                    if saved_monitoring:
                        logger.info(f"✅ Verified {address}: origin_block_number = {saved_monitoring.origin_block_number}")
                    else:
                        logger.error(f"❌ Failed to find saved monitoring entry for {address}")
            else:
                db.rollback()
                return
            
            # Step 2: Import to Bitcoin Core if available
            if btc_service and added_addresses:
                try:
                    # Load wallet
                    try:
                        btc_service.load_watch_wallet()
                    except Exception as e:
                        if "is already loaded" not in str(e):
                            raise
                    
                    # Import addresses using importmulti
                    success = self._import_addresses_to_bitcoin_core(
                        btc_service, added_addresses, progress, len(selected_addresses)
                    )
                    
                    if not success and not progress.wasCanceled():
                        QMessageBox.warning(
                            self,
                            "Import Warning",
                            "Addresses were added to monitoring but failed to import to Bitcoin Core wallet.\n"
                            "You can import them later using the import tools."
                        )
                except Exception as e:
                    if not progress.wasCanceled():
                        QMessageBox.warning(
                            self,
                            "Import Warning",
                            f"Addresses were added to monitoring but failed to import to Bitcoin Core:\n{str(e)}\n\n"
                            "You can import them later using the import tools."
                        )
            
            # Complete progress
            if not progress.wasCanceled():
                progress.setValue(total_steps)
                
                # Refresh both tables
                self.check_unmonitored_addresses()
                self.load_addresses()
                
                # Show success message
                if btc_service:
                    QMessageBox.information(
                        self,
                        "Success",
                        f"Successfully added {len(added_addresses)} addresses to monitoring and initiated import to Bitcoin Core.\n\n"
                        "The import/rescan process is running in the background on your Bitcoin Core node."
                    )
                else:
                    QMessageBox.information(
                        self,
                        "Success",
                        f"Added {len(added_addresses)} addresses to monitoring.\n\n"
                        "Import them to Bitcoin Core later using the import tools."
                    )
            
        except Exception as e:
            db.rollback()
            QMessageBox.critical(self, "Error", f"Failed to add addresses: {str(e)}")
        finally:
            db.close()
    
    def _import_addresses_to_bitcoin_core(self, btc_service, addresses_with_blocks, progress, db_count):
        """Import addresses to Bitcoin Core using importmulti with timestamps"""
        try:
            progress.setLabelText("Preparing Bitcoin Core import requests...")
            QApplication.processEvents()
            
            # Prepare importmulti requests
            import_requests = []
            
            for i, (address, origin_block) in enumerate(addresses_with_blocks):
                if progress.wasCanceled():
                    return False
                
                progress.setLabelText(f"Preparing import ({i+1}/{len(addresses_with_blocks)}):\n{address}")
                progress.setValue(db_count + i)
                QApplication.processEvents()
                
                # Get timestamp for origin block
                start_timestamp = None
                if origin_block:
                    try:
                        block_hash = btc_service._call_rpc("getblockhash", [origin_block])
                        block_info = btc_service._call_rpc("getblockheader", [block_hash])
                        start_timestamp = block_info.get('time', None)
                        if start_timestamp:
                            start_date = datetime.fromtimestamp(start_timestamp)
                            logger.info(f"Address {address} origin block {origin_block} timestamp: {start_date}")
                    except Exception as e:
                        logger.warning(f"Couldn't get timestamp for block {origin_block}: {e}")
                
                # Use recent timestamp (1 month ago) instead of genesis if no origin block
                if not start_timestamp:
                    from datetime import datetime, timedelta
                    one_month_ago = datetime.now() - timedelta(days=30)
                    start_timestamp = int(one_month_ago.timestamp())
                    logger.info(f"No origin block available for {address}, using recent timestamp (1 month ago): {start_timestamp}")
                
                # Add to batch with timestamp
                import_requests.append({
                    "scriptPubKey": {"address": address},
                    "timestamp": start_timestamp,
                    "watchonly": True,
                    "label": f"monitored-{address[:8]}",
                    "rescan": True
                })
            
            if progress.wasCanceled() or not import_requests:
                return False
            
            # Execute importmulti
            progress.setLabelText(f"Importing {len(import_requests)} addresses to Bitcoin Core...\n"
                                 "This will start a rescan process in the background.")
            progress.setValue(db_count + len(addresses_with_blocks))
            QApplication.processEvents()
            
            # Use direct HTTP call with timeout handling
            encoded_wallet_path = urllib.parse.quote(btc_service.wallet_path)
            import_url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_path}"
            
            headers = {'content-type': 'application/json'}
            payload = {
                "jsonrpc": "1.0",
                "id": "crypto-basis-monitor",
                "method": "importmulti",
                "params": [import_requests, {"rescan": True}]
            }
            
            auth = (btc_service.user, btc_service.password)
            
            try:
                # Use a short timeout as we expect this to timeout (async behavior)
                response = requests.post(import_url, json=payload, headers=headers, auth=auth, timeout=30)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('error'):
                        logger.error(f"Import failed: {result['error']}")
                        return False
                    
                    # Process results
                    if 'result' in result and result['result']:
                        result_list = result['result']
                        success_count = sum(1 for r in result_list if r.get('success'))
                        logger.info(f"Successfully imported {success_count} of {len(import_requests)} addresses")
                        
                        # Log errors if any
                        for i, r in enumerate(result_list):
                            if not r.get('success'):
                                addr = addresses_with_blocks[i][0]
                                error = r.get('error', {}).get('message', 'Unknown error')
                                logger.error(f"Failed to import {addr}: {error}")
                        
                        return success_count > 0
                else:
                    logger.error(f"HTTP error: {response.status_code}, Response: {response.text}")
                    return False
                    
            except requests.exceptions.Timeout:
                # Timeout is expected and fine - operation continues on node
                logger.info("Import request timed out as expected - rescan is running on Bitcoin Core")
                return True
                
        except Exception as e:
            if "timeout" in str(e).lower():
                logger.info("Import timed out as expected - rescan is running on Bitcoin Core")
                return True
            else:
                logger.error(f"Error during Bitcoin Core import: {e}")
                return False
        
        return True 