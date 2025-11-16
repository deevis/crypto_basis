from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QPushButton, QTableWidget, QTableWidgetItem, QLabel,
                           QSplitter, QFileDialog, QMessageBox, QDialog, QComboBox,
                           QDialogButtonBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from db_config import get_db, SessionLocal
from models import Transaction, OperationType, WalletTransfer, TransactionFulfillment, ExchangeTransfer
from sqlalchemy import func, case, and_
from data_importer import import_csv
from btc_importer import import_btc_utxos, UTXOImportDialog
from export_dialog import ExportDialog
from fulfillment_dialog import FulfillmentDialog
from transfer_dialog import TransferDialog
from sqlalchemy.orm import Session
from exchange_transfer_dialog import ExchangeTransferDialog
from btc_service import BTCService
from transaction_details_dialog import TransactionDetailsDialog
from price_service import PriceService
import logging

logger = logging.getLogger(__name__)

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            # Strip currency symbols and commas, then convert to float
            self_value = float(self.text().replace('$', '').replace(',', '').replace('%', ''))
            other_value = float(other.text().replace('$', '').replace(',', '').replace('%', ''))
            return self_value < other_value
        except ValueError:
            return super().__lt__(other)

class PercentageTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            # Strip percentage sign and convert to float
            self_value = float(self.text().replace('%', ''))
            other_value = float(other.text().replace('%', ''))
            return self_value < other_value
        except ValueError:
            return super().__lt__(other)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Crypto Basis")
        self.resize(1200, 800)
        
        # Create price service instance
        self.price_service = PriceService()
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create filter section
        filter_layout = QHBoxLayout()
        
        wallet_label = QLabel("Wallet:")
        self.wallet_filter = QComboBox()
        coin_label = QLabel("Coin:")
        self.coin_filter = QComboBox()
        
        filter_layout.addWidget(wallet_label)
        filter_layout.addWidget(self.wallet_filter)
        filter_layout.addWidget(coin_label)
        filter_layout.addWidget(self.coin_filter)
        filter_layout.addStretch()  # This pushes everything to the left
        
        layout.addLayout(filter_layout)
        
        # Create splitter for summary and transactions
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)
        
        # Create summary panel
        summary_panel = QWidget()
        summary_layout = QVBoxLayout(summary_panel)
        summary_label = QLabel("Summary")
        summary_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        summary_layout.addWidget(summary_label)
        
        # Create summary table
        self.summary_table = QTableWidget()
        self.setup_summary_table()
        summary_layout.addWidget(self.summary_table)
        summary_panel.setLayout(summary_layout)
        
        # Create transactions panel
        transactions_panel = QWidget()
        transactions_layout = QVBoxLayout(transactions_panel)
        transactions_label = QLabel("Transactions")
        transactions_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        transactions_layout.addWidget(transactions_label)
        
        # Create transactions table
        self.transactions_table = QTableWidget()
        self.setup_transactions_table()
        transactions_layout.addWidget(self.transactions_table)
        transactions_panel.setLayout(transactions_layout)
        
        # Add panels to splitter
        splitter.addWidget(summary_panel)
        splitter.addWidget(transactions_panel)
        
        # Load data
        self.load_summary()
        self.load_transactions()  # Load all transactions initially
        self.summary_table.itemSelectionChanged.connect(self.on_summary_selection_changed)
        
        # Connect filter change signals
        self.coin_filter.currentTextChanged.connect(self.on_filter_changed)
        self.wallet_filter.currentTextChanged.connect(self.on_filter_changed)
        
        # Load filters
        self.load_filters()
        
        # Create menu bar
        self.setup_menu_bar()
    
    def setup_menu_bar(self):
        """Setup the application menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        import_action = file_menu.addAction("&Import Transactions...")
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self.import_transactions)
        
        import_btc_action = file_menu.addAction("Import &BTC UTXOs...")
        import_btc_action.triggered.connect(self.show_btc_import_dialog)
        
        file_menu.addSeparator()
        
        export_action = file_menu.addAction("&Export...")
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.show_export_dialog)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        refresh_action = view_menu.addAction("&Refresh")
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_all)
        
        view_menu.addSeparator()
        
        totals_action = view_menu.addAction("Show &Totals...")
        totals_action.triggered.connect(self.show_totals)
        
        gains_action = view_menu.addAction("Show &Realized Gains...")
        gains_action.triggered.connect(self.show_realized_gains)
        
        portfolio_action = view_menu.addAction("Show &Portfolio Performance...")
        portfolio_action.triggered.connect(self.show_portfolio_performance)
        
        exchange_activity_action = view_menu.addAction("Show &Exchange Activity...")
        exchange_activity_action.triggered.connect(self.show_exchange_activity)
        
        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        
        # Add Bitcoin submenu
        bitcoin_menu = tools_menu.addMenu("&Bitcoin")
        
        # Add Address Monitoring action to Bitcoin submenu
        address_monitor_action = bitcoin_menu.addAction("Address &Monitoring...")
        address_monitor_action.triggered.connect(self.show_btc_address_monitor)
        
        bitcoin_menu.addSeparator()
        
        # Move existing BTC actions to Bitcoin submenu
        add_btc_action = bitcoin_menu.addAction("Add &BTC Transaction...")
        add_btc_action.triggered.connect(self.show_add_btc_dialog)
        
        import_btc_action = bitcoin_menu.addAction("Import BTC &UTXOs...")
        import_btc_action.triggered.connect(self.show_btc_import_dialog)
        
        tools_menu.addSeparator()
        
        settings_action = tools_menu.addAction("&Settings...")
        settings_action.triggered.connect(self.show_settings_dialog)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self.show_about)
    
    def setup_summary_table(self):
        headers = ["Wallet", "Coin", "Total IN", "Total OUT", "Balance", 
                  "Avg Cost Basis", "Current Price", "Cost Basis Value", "Current Value", 
                  "% Gain", "Unlinked OUT"]
        self.summary_table.setColumnCount(len(headers))
        self.summary_table.setHorizontalHeaderLabels(headers)
        self.summary_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.summary_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.summary_table.setSortingEnabled(True)
        
    def setup_transactions_table(self):
        self.transaction_headers = ["Wallet", "Coin", "Type", "Date", "Amount", 
                                  "Cost Basis", "Current Price", "Cost Value", "Current Value",
                                  "% Gain", "Available", "Status", "Linked", "Memo", "Actions"]
        
        self.transactions_table.setColumnCount(len(self.transaction_headers))
        self.transactions_table.setHorizontalHeaderLabels(self.transaction_headers)
        self.transactions_table.setColumnWidth(len(self.transaction_headers)-1, 200)

    def load_summary(self):
        db = SessionLocal()
        try:
            # Get current prices for all coins using instance price service
            all_coins = [coin[0] for coin in db.query(Transaction.currency_ticker).distinct().all()]
            current_prices = self.price_service.get_current_prices(all_coins)
            
            # Subquery to get OUT transactions that are neither fulfilled nor transferred
            unlinked_subquery = db.query(Transaction.id).filter(
                Transaction.operation_type == OperationType.OUT
            ).outerjoin(
                TransactionFulfillment,
                TransactionFulfillment.out_transaction_id == Transaction.id
            ).outerjoin(
                WalletTransfer,
                WalletTransfer.out_transaction_id == Transaction.id
            ).group_by(
                Transaction.id
            ).having(
                and_(
                    func.coalesce(func.sum(TransactionFulfillment.out_transaction_percent_filled), 0) < 100,
                    func.count(WalletTransfer.id) == 0
                )
            ).subquery()
            
            # Start with base query
            query = db.query(
                Transaction.wallet_name,
                Transaction.currency_ticker,
                func.sum(
                    case(
                        (Transaction.operation_type == OperationType.IN, Transaction.operation_amount),
                        else_=0
                    )
                ).label('total_in'),
                func.sum(
                    case(
                        (Transaction.operation_type == OperationType.OUT, Transaction.operation_amount),
                        else_=0
                    )
                ).label('total_out'),
                func.sum(
                    case(
                        (Transaction.operation_type == OperationType.IN, 
                         Transaction.operation_amount * Transaction.cost_basis),
                        else_=0
                    )
                ).label('total_cost_basis'),
                func.count(
                    case(
                        (Transaction.id.in_(unlinked_subquery), 1),
                    )
                ).label('unlinked_out')
            )
            
            # Apply filters
            selected_coin = self.coin_filter.currentText()
            if selected_coin != "All Coins":
                query = query.filter(Transaction.currency_ticker == selected_coin)
                
            selected_wallet = self.wallet_filter.currentText()
            if selected_wallet != "All Wallets":
                query = query.filter(Transaction.wallet_name == selected_wallet)
            
            # Complete query with group by
            summary = query.group_by(
                Transaction.wallet_name,
                Transaction.currency_ticker
            ).all()
            
            self.summary_table.setSortingEnabled(False)  # Temporarily disable sorting while loading
            self.summary_table.setRowCount(len(summary))
            
            for i, row in enumerate(summary):
                wallet, currency, total_in, total_out, total_cost_basis, unlinked = row
                total_in = total_in or 0
                total_out = total_out or 0
                total_cost_basis = total_cost_basis or 0
                balance = total_in - total_out
                
                # Get current price
                current_price = current_prices.get(currency, 0)
                
                # Calculate values
                avg_cost_basis = (total_cost_basis / total_in) if total_in > 0 else 0
                cost_basis_value = balance * avg_cost_basis
                current_value = balance * current_price
                
                # Calculate gain percentage
                gain_percent = ((current_value / cost_basis_value) - 1) * 100 if cost_basis_value > 0 else 0
                
                # Create items with appropriate types for sorting
                items = [
                    QTableWidgetItem(wallet),
                    QTableWidgetItem(currency),
                    NumericTableWidgetItem(f"{total_in:.8f}"),
                    NumericTableWidgetItem(f"{total_out:.8f}"),
                    NumericTableWidgetItem(f"{balance:.8f}"),
                    NumericTableWidgetItem(f"${avg_cost_basis:,.2f}"),
                    NumericTableWidgetItem(f"${current_price:,.2f}"),
                    NumericTableWidgetItem(f"${cost_basis_value:,.2f}"),
                    NumericTableWidgetItem(f"${current_value:,.2f}"),
                    PercentageTableWidgetItem(f"{gain_percent:,.2f}%"),  # Changed to PercentageTableWidgetItem
                    NumericTableWidgetItem(str(unlinked))
                ]
                
                for col, item in enumerate(items):
                    self.summary_table.setItem(i, col, item)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight if col > 1 else Qt.AlignmentFlag.AlignLeft)
                    
                    # Color the gain percentage
                    if col == 9:  # Gain column
                        if gain_percent > 0:
                            item.setForeground(Qt.GlobalColor.darkGreen)
                        elif gain_percent < 0:
                            item.setForeground(Qt.GlobalColor.red)
                
                # Highlight rows with unlinked transactions
                if unlinked > 0:
                    for col in range(self.summary_table.columnCount()):
                        self.summary_table.item(i, col).setBackground(QColor("#fff3cd"))
            
            # Resize columns to content
            self.summary_table.resizeColumnsToContents()
            self.summary_table.setSortingEnabled(True)  # Re-enable sorting
        finally:
            db.close()
    
    def on_summary_selection_changed(self):
        selected_items = self.summary_table.selectedItems()
        if not selected_items:
            return
        
        # Get wallet and currency from selected row
        row = self.summary_table.row(selected_items[0])
        wallet = self.summary_table.item(row, 0).text()
        currency = self.summary_table.item(row, 1).text()
        
        # Load transactions for selected wallet/currency
        self.load_transactions(wallet, currency)
    
    def load_transactions(self, wallet=None, currency=None):
        """Load transactions with default sort by date descending"""
        db = SessionLocal()
        try:
            # Get current prices using instance price service
            all_coins = [coin[0] for coin in db.query(Transaction.currency_ticker).distinct().all()]
            current_prices = self.price_service.get_current_prices(all_coins)
            
            query = db.query(Transaction)
            
            if wallet and currency:
                # Filter by specific wallet and currency (from summary selection)
                query = query.filter(
                    Transaction.wallet_name == wallet,
                    Transaction.currency_ticker == currency
                )
            else:
                # Apply the filter controls when no specific selection
                selected_coin = self.coin_filter.currentText()
                if selected_coin != "All Coins":
                    query = query.filter(Transaction.currency_ticker == selected_coin)
                    
                selected_wallet = self.wallet_filter.currentText()
                if selected_wallet != "All Wallets":
                    query = query.filter(Transaction.wallet_name == selected_wallet)
            
            # Add default ordering by date descending
            query = query.order_by(Transaction.operation_date.desc())
                
            transactions = query.all()
            
            self.transactions_table.setSortingEnabled(False)
            self.transactions_table.setRowCount(len(transactions))
            
            # Clear all cell widgets in the Actions column first
            actions_column = len(["Wallet", "Coin", "Type", "Date", "Amount", "Cost Basis", 
                                "Current Price", "Cost Value", "Current Value", "% Gain", "Available",
                                "Status", "Linked", "Memo", "Actions"]) - 1
            for row in range(self.transactions_table.rowCount()):
                self.transactions_table.removeCellWidget(row, actions_column)
            
            for i, tx in enumerate(transactions):
                # Calculate current value
                current_price = current_prices.get(tx.currency_ticker, 0)
                current_value = tx.operation_amount * current_price
                cost_value = tx.operation_amount * tx.cost_basis if tx.cost_basis else 0
                
                # Calculate gain percentage
                gain_percent = ((current_value / cost_value) - 1) * 100 if cost_value > 0 else 0
                
                # Get transfer info if it exists
                transfer = None
                exchange_transfer = None
                is_linked = False
                
                if tx.operation_type == OperationType.OUT:
                    # Check for wallet transfer
                    transfer = db.query(WalletTransfer)\
                        .filter(WalletTransfer.out_transaction_id == tx.id)\
                        .filter(WalletTransfer.out_transaction.has(currency_ticker=tx.currency_ticker))\
                        .first()
                    
                    # Check for exchange transfer
                    exchange_transfer = db.query(ExchangeTransfer)\
                        .filter(ExchangeTransfer.out_transaction_id == tx.id)\
                        .first()
                        
                    total_percent = db.query(func.sum(TransactionFulfillment.out_transaction_percent_filled))\
                        .filter(TransactionFulfillment.out_transaction_id == tx.id)\
                        .scalar() or 0
                        
                    is_linked = transfer is not None or exchange_transfer is not None or abs(100 - total_percent) < 0.01
                
                elif tx.operation_type == OperationType.IN:
                    transfer = db.query(WalletTransfer)\
                        .filter(WalletTransfer.in_transaction_id == tx.id)\
                        .filter(WalletTransfer.in_transaction.has(currency_ticker=tx.currency_ticker))\
                        .first()
                    is_linked = transfer is not None
                
                row_items = [
                    QTableWidgetItem(tx.wallet_name),
                    QTableWidgetItem(tx.currency_ticker),
                    QTableWidgetItem(tx.operation_type.value),
                    QTableWidgetItem(tx.operation_date.strftime('%Y-%m-%d %H:%M')),
                    NumericTableWidgetItem(f"{tx.operation_amount:.8f}"),
                    NumericTableWidgetItem(f"${tx.cost_basis:,.2f}"),
                    NumericTableWidgetItem(f"${current_price:,.2f}"),
                    NumericTableWidgetItem(f"${cost_value:,.2f}"),
                    NumericTableWidgetItem(f"${current_value:,.2f}"),
                    PercentageTableWidgetItem(f"{gain_percent:,.2f}%"),  # Changed to PercentageTableWidgetItem
                    NumericTableWidgetItem(f"{tx.available_to_spend:.8f}" if tx.available_to_spend is not None else ""),
                    QTableWidgetItem(tx.status),
                    QTableWidgetItem("Yes" if is_linked else "No"),
                    QTableWidgetItem(tx.memo or ""),
                ]
                
                for col, item in enumerate(row_items):
                    self.transactions_table.setItem(i, col, item)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight if col in [4, 5, 6, 7, 8, 9, 10] else Qt.AlignmentFlag.AlignLeft)
                    
                    # Color the gain percentage
                    if col == 9:  # Gain column
                        if gain_percent > 0:
                            item.setForeground(Qt.GlobalColor.darkGreen)
                        elif gain_percent < 0:
                            item.setForeground(Qt.GlobalColor.red)
                
                # Clear any existing widget in the Actions column
                self.transactions_table.removeCellWidget(i, len(row_items))
                
                # Add action buttons
                button_widget = QWidget()
                button_layout = QHBoxLayout(button_widget)
                button_layout.setContentsMargins(2, 2, 2, 2)  # Reduced margins
                button_layout.setSpacing(2)
                
                # Add TX Info button for BTC transactions
                if tx.currency_ticker == "BTC" and tx.operation_hash:
                    # logger.debug(f"Adding TX Info button for {tx.operation_hash}")
                    tx_info_btn = QPushButton("TX Info")
                    tx_info_btn.setFixedWidth(60)  # Set fixed width
                    tx_info_btn.clicked.connect(lambda checked, txid=tx.operation_hash: self.show_tx_info(txid))
                    button_layout.addWidget(tx_info_btn)
                
                # Add Edit button for all transactions
                edit_button = QPushButton("Edit")
                edit_button.setFixedWidth(40)  # Set fixed width
                edit_button.clicked.connect(lambda checked, tx=tx: self.show_edit_transaction_dialog(tx))
                button_layout.addWidget(edit_button)
                
                # Add other buttons based on transaction type
                if tx.operation_type == OperationType.OUT:
                    fulfill_button = QPushButton("Manage Fulfillments")
                    fulfill_button.clicked.connect(lambda checked, tx_id=tx.id: self.show_fulfillment_dialog(tx_id))
                    button_layout.addWidget(fulfill_button)
                    
                    if exchange_transfer:
                        # Show exchange info and manage button
                        info_label = QLabel(f"Sent to {exchange_transfer.exchange.name}")
                        manage_button = QPushButton("Edit Exchange")
                        manage_button.clicked.connect(
                            lambda checked, t=exchange_transfer: 
                            self.show_exchange_transfer_dialog(tx.id, t)
                        )
                        
                        button_layout.addWidget(info_label)
                        button_layout.addWidget(manage_button)
                    elif transfer:
                        # Show wallet transfer info and unlink button
                        linked_wallet = transfer.in_transaction.wallet_name
                        info_label = QLabel(f"Linked to {linked_wallet}")
                        unlink_button = QPushButton("Unlink Transfer")
                        unlink_button.clicked.connect(lambda checked, t=transfer: self.unlink_transfer(t))
                        
                        button_layout.addWidget(info_label)
                        button_layout.addWidget(unlink_button)
                    else:
                        # Add Link Transfer and Send to Exchange buttons
                        transfer_button = QPushButton("Link Transfer")
                        exchange_button = QPushButton("Send to Exchange")
                        
                        transfer_button.clicked.connect(lambda checked, tx_id=tx.id: self.show_transfer_dialog(tx_id))
                        exchange_button.clicked.connect(lambda checked, tx_id=tx.id: self.show_exchange_transfer_dialog(tx_id))
                        
                        button_layout.addWidget(transfer_button)
                        button_layout.addWidget(exchange_button)
                    
                    self.transactions_table.setCellWidget(i, len(row_items), button_widget)
                
                # Add transfer info for IN transactions
                elif tx.operation_type == OperationType.IN and transfer:
                    info_label = QLabel(f"Transfer from {transfer.out_transaction.wallet_name}")
                    self.transactions_table.setCellWidget(i, len(row_items), info_label)
                
                # Handle NFT_IN transactions - show as disabled
                if tx.operation_type == OperationType.NFT_IN:
                    for col in range(len(row_items) + 1):  # +1 for action column
                        item = self.transactions_table.item(i, col)
                        if item:
                            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                            item.setBackground(QColor("#f0f0f0"))
                
                # Highlight unlinked OUT transactions
                if tx.operation_type == OperationType.OUT and not is_linked:
                    for col in range(len(row_items) + 1):  # +1 for action column
                        item = self.transactions_table.item(i, col)
                        if item:
                            item.setBackground(Qt.GlobalColor.yellow)
                
                # Make sure the widget is properly set in the table
                self.transactions_table.setCellWidget(i, len(row_items), button_widget)
                
                # Set row height to accommodate buttons
                self.transactions_table.setRowHeight(i, 30)
            
            self.transactions_table.resizeColumnsToContents()
            self.transactions_table.setSortingEnabled(True)
            
            # Set minimum window width to accommodate new columns
            self.setMinimumWidth(1400)  # Increased from previous value
        finally:
            db.close()
    
    def show_link_dialog(self):
        # TODO: Implement transaction linking dialog
        pass 

    def import_transactions(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Import Transactions",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_name:
            try:
                import_csv(file_name)
                self.load_filters()  # Refresh filters
                self.load_summary()  # Refresh the display
                QMessageBox.information(
                    self,
                    "Success",
                    "Transactions imported successfully!"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to import transactions: {str(e)}"
                )

    def import_btc_utxos(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Import BTC UTXOs",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_name:
            # Show dialog to get wallet and account names
            dialog = UTXOImportDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                values = dialog.get_values()
                
                # Validate input
                if not values['wallet_name'] or not values['account_name']:
                    QMessageBox.warning(
                        self,
                        "Invalid Input",
                        "Both wallet name and account name are required."
                    )
                    return
                
                try:
                    import_btc_utxos(
                        file_name,
                        values['wallet_name'],
                        values['account_name']
                    )
                    self.load_filters()  # Refresh filters
                    self.load_summary()  # Refresh the display
                    QMessageBox.information(
                        self,
                        "Success",
                        "BTC UTXOs imported successfully!"
                    )
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "Error",
                        f"Failed to import BTC UTXOs: {str(e)}"
                    )

    def show_export_dialog(self):
        dialog = ExportDialog(self)
        dialog.exec()

    def load_filters(self):
        """Load available coins and wallets into filters"""
        db = SessionLocal()
        try:
            # Get unique coins
            coins = db.query(Transaction.currency_ticker).distinct().order_by(Transaction.currency_ticker).all()
            self.coin_filter.clear()
            self.coin_filter.addItem("All Coins")
            for coin in coins:
                self.coin_filter.addItem(coin[0])
                
            # Get unique wallets
            wallets = db.query(Transaction.wallet_name).distinct().order_by(Transaction.wallet_name).all()
            self.wallet_filter.clear()
            self.wallet_filter.addItem("All Wallets")
            for wallet in wallets:
                self.wallet_filter.addItem(wallet[0])
        finally:
            db.close()
    
    def on_filter_changed(self):
        """Handle changes to either filter"""
        self.load_summary()
        # Clear summary selection and load filtered transactions
        self.summary_table.clearSelection()
        self.load_transactions()

    def show_totals(self):
        from totals_dialog import TotalsDialog
        dialog = TotalsDialog(self)
        dialog.exec()

    def show_fulfillment_dialog(self, transaction_id):
        dialog = FulfillmentDialog(transaction_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_transactions()  # Refresh transactions
            self.load_summary()       # Refresh summary

    def show_transfer_dialog(self, transaction_id):
        dialog = TransferDialog(transaction_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_transactions()  # Refresh transactions
            self.load_summary()       # Refresh summary

    def unlink_transfer(self, transfer):
        """Unlink a wallet transfer after confirmation"""
        try:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText("Are you sure you want to unlink this transfer?")
            msg.setInformativeText(
                f"This will unlink the transfer between wallets "
                f"{transfer.out_transaction.wallet_name} and {transfer.in_transaction.wallet_name}"
            )
            msg.setWindowTitle("Confirm Unlink")
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if msg.exec() == QMessageBox.StandardButton.Yes:
                session = SessionLocal()
                try:
                    # Get a fresh copy of the transfer in our new session
                    transfer_to_delete = session.query(WalletTransfer).get(transfer.id)
                    
                    # Reset the IN transaction's cost basis
                    in_transaction = session.query(Transaction).get(transfer_to_delete.in_transaction_id)
                    in_transaction.cost_basis = 0  # Or some other default value
                    
                    # Delete the transfer
                    session.delete(transfer_to_delete)
                    session.commit()
                    
                    QMessageBox.information(
                        self,
                        "Success",
                        "Transfer has been unlinked successfully."
                    )
                    
                    # Refresh both displays
                    self.load_transactions()
                    self.load_summary()
                    
                except Exception as e:
                    session.rollback()
                    QMessageBox.critical(self, "Error", f"Failed to unlink transfer: {str(e)}")
                finally:
                    session.close()
                    
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to unlink transfer: {str(e)}")

    def show_exchange_transfer_dialog(self, transaction_id, transfer=None):
        dialog = ExchangeTransferDialog(transaction_id, self, transfer)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_transactions()  # Refresh transactions
            self.load_summary()       # Refresh summary

    def show_settings_dialog(self):
        from settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        dialog.exchanges_updated.connect(self.on_exchanges_updated)
        dialog.exec()
    
    def on_exchanges_updated(self):
        """Refresh any open dialogs that use exchanges"""
        # Find and refresh any open ExchangeTransferDialog
        for child in self.findChildren(QDialog):
            if isinstance(child, ExchangeTransferDialog):
                child.load_exchanges()

    def refresh_all(self):
        """Refresh all data displays"""
        self.load_filters()
        self.load_summary()
        
        # If a row is selected in summary, refresh transactions for that selection
        if self.summary_table.selectedItems():
            self.on_summary_selection_changed()
        else:
            # No summary selection, load transactions with current filters
            self.load_transactions()
    
    def show_btc_import_dialog(self):
        dialog = UTXOImportDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_all()
    
    def show_about(self):
        QMessageBox.about(
            self,
            "About Crypto Basis",
            """<h3>Crypto Basis</h3>
            <p>A tool for tracking cryptocurrency cost basis and capital gains.</p>
            <p>Version: 1.0</p>
            <p>© 2024</p>"""
        )

    def show_realized_gains(self):
        from realized_gains_dialog import RealizedGainsDialog
        dialog = RealizedGainsDialog(self)
        dialog.exec()

    def show_add_btc_dialog(self):
        """Show dialog to add a new BTC transaction"""
        # Get currently selected wallet from summary table
        selected_items = self.summary_table.selectedItems()
        wallet_name = None
        currency = None
        
        if selected_items:
            row = self.summary_table.row(selected_items[0])
            wallet_name = self.summary_table.item(row, 0).text()
            currency = self.summary_table.item(row, 1).text()
        
        # If no selection or not BTC, ask user to select a wallet
        if not wallet_name or currency != "BTC":
            wallet_name = self.prompt_for_wallet()
            if not wallet_name:
                return
        
        from add_btc_dialog import AddBTCDialog
        dialog = AddBTCDialog(wallet_name, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_all()
    
    def prompt_for_wallet(self):
        """Show dialog to select a wallet"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Wallet")
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # Add wallet selection combo
        wallet_combo = QComboBox()
        db = SessionLocal()
        try:
            wallets = db.query(Transaction.wallet_name)\
                .filter(Transaction.currency_ticker == "BTC")\
                .distinct()\
                .order_by(Transaction.wallet_name)\
                .all()
            
            for wallet in wallets:
                wallet_combo.addItem(wallet[0])
        finally:
            db.close()
        
        layout.addWidget(QLabel("Select wallet for new BTC transaction:"))
        layout.addWidget(wallet_combo)
        
        # Add buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return wallet_combo.currentText()
        return None

    def show_add_transaction_dialog(self):
        """Show dialog to add a new manual transaction"""
        # Get currently selected wallet/currency from summary table
        selected_items = self.summary_table.selectedItems()
        wallet_name = None
        currency = None
        
        if selected_items:
            row = self.summary_table.row(selected_items[0])
            wallet_name = self.summary_table.item(row, 0).text()
            currency = self.summary_table.item(row, 1).text()
        
        from add_transaction_dialog import AddTransactionDialog
        dialog = AddTransactionDialog(wallet_name, currency, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_all()

    def show_edit_transaction_dialog(self, transaction):
        """Show dialog to edit an existing transaction"""
        from add_transaction_dialog import AddTransactionDialog
        dialog = AddTransactionDialog(
            wallet_name=transaction.wallet_name,
            currency=transaction.currency_ticker,
            operation_type=transaction.operation_type.value,
            transaction=transaction,  # Pass the transaction for editing
            parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_all()

    def show_exchange_activity(self):
        from exchange_activity_dialog import ExchangeActivityDialog
        dialog = ExchangeActivityDialog(self)
        dialog.exec()

    def show_tx_info(self, txid):
        """Show transaction details dialog for a BTC transaction"""
        try:
            btc_service = BTCService()
            tx_data = btc_service.get_raw_transaction_info(txid)
            
            # Get the transaction object from the database
            db = SessionLocal()
            try:
                transaction = db.query(Transaction).filter(
                    Transaction.operation_hash == txid
                ).first()
                
                # Update block info if needed
                if transaction and not transaction.block_number:
                    btc_service.update_transaction_block_info(transaction)
                    db.commit()
            finally:
                db.close()
            
            dialog = TransactionDetailsDialog(tx_data, address=None, transaction=transaction)
            dialog.exec()
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to get transaction info: {str(e)}"
            )

    def show_portfolio_performance(self):
        from portfolio_value_dialog import PortfolioValueDialog
        dialog = PortfolioValueDialog(self)
        dialog.exec()

    def show_btc_address_monitor(self):
        """Show the Bitcoin address monitoring dialog"""
        from btc_address_monitor_dialog import BTCAddressMonitorDialog
        dialog = BTCAddressMonitorDialog(self)
        dialog.exec()