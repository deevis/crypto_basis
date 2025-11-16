from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QTableWidget, QTableWidgetItem, QComboBox, QHeaderView,
                           QMessageBox, QWidget)
from PyQt6.QtCore import Qt
from db_config import SessionLocal
from models import Exchange, ExchangeTransfer, Transaction, CapitalGainsTerm
from sqlalchemy import func

class ExchangeActivityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = SessionLocal()
        
        self.setWindowTitle("Exchange Activity")
        self.setModal(True)
        self.setMinimumWidth(1200)
        self.setMinimumHeight(600)
        
        layout = QVBoxLayout(self)
        
        # Exchange filter
        filter_layout = QHBoxLayout()
        self.exchange_combo = QComboBox()
        self.exchange_combo.addItem("All Exchanges")
        self.load_exchanges()
        self.exchange_combo.currentIndexChanged.connect(self.load_activity)
        
        filter_layout.addWidget(QLabel("Exchange:"))
        filter_layout.addWidget(self.exchange_combo)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Activity table
        self.table = QTableWidget()
        self.setup_table()
        layout.addWidget(self.table)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        
        # Load initial data
        self.load_activity()
    
    def load_exchanges(self):
        exchanges = self.session.query(Exchange)\
            .order_by(Exchange.name)\
            .all()
        
        for exchange in exchanges:
            self.exchange_combo.addItem(exchange.name, exchange.id)
    
    def setup_table(self):
        headers = [
            "Date Sent", "Exchange", "Currency", "Amount Sent", "Sale Date", 
            "Sale Amount", "Sale Price", "Cost Basis", "Fee", "Realized Gain",
            "Term Type", "Status", "Actions"
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSortingEnabled(True)
        
        header = self.table.horizontalHeader()
        for i in range(len(headers)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    
    def load_activity(self):
        selected_exchange_id = self.exchange_combo.currentData()
        
        # Base query
        query = self.session.query(
            ExchangeTransfer, Transaction
        ).join(
            Transaction,
            ExchangeTransfer.out_transaction_id == Transaction.id
        ).join(
            Exchange,
            ExchangeTransfer.exchange_id == Exchange.id
        )
        
        # Apply exchange filter if selected
        if selected_exchange_id:
            query = query.filter(ExchangeTransfer.exchange_id == selected_exchange_id)
        
        # Order by dates
        transfers = query.order_by(Transaction.operation_date.desc()).all()
        
        self.table.setRowCount(len(transfers))
        
        for i, (transfer, tx) in enumerate(transfers):
            # Calculate status
            if not transfer.sale_date:
                status = "Pending Sale"
            elif not transfer.sale_amount:
                status = "Sale Date Set"
            else:
                status = "Completed"
            
            # Format realized gain with color
            if transfer.realized_gain:
                gain_text = f"${transfer.realized_gain:,.2f}"
                gain_color = Qt.GlobalColor.darkGreen if transfer.realized_gain > 0 else Qt.GlobalColor.red
            else:
                gain_text = ""
                gain_color = Qt.GlobalColor.black
            
            items = [
                QTableWidgetItem(tx.operation_date.strftime('%Y-%m-%d')),
                QTableWidgetItem(transfer.exchange.name),
                QTableWidgetItem(tx.currency_ticker),
                QTableWidgetItem(f"{tx.operation_amount:.8f}"),
                QTableWidgetItem(transfer.sale_date.strftime('%Y-%m-%d') if transfer.sale_date else ""),
                QTableWidgetItem(f"{transfer.sale_amount:.8f}" if transfer.sale_amount else ""),
                QTableWidgetItem(f"${transfer.sale_price:,.2f}" if transfer.sale_price else ""),
                QTableWidgetItem(f"${tx.cost_basis:,.2f}"),
                QTableWidgetItem(f"${transfer.fee:,.2f}" if transfer.fee else "$0.00"),
                QTableWidgetItem(gain_text),
                QTableWidgetItem(transfer.term_type.value if transfer.term_type else ""),
                QTableWidgetItem(status)
            ]
            
            # Set alignment and colors
            for col, item in enumerate(items):
                self.table.setItem(i, col, item)
                if col in [3, 5, 6, 7, 8, 9]:  # Numeric columns
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == 9:  # Realized gain column
                    item.setForeground(gain_color)
            
            # Add action buttons
            button_widget = self.create_action_buttons(transfer, tx)
            self.table.setCellWidget(i, len(items), button_widget)
    
    def create_action_buttons(self, transfer, tx):
        button_widget = QWidget()
        layout = QHBoxLayout(button_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(lambda: self.edit_transfer(transfer, tx))
        layout.addWidget(edit_button)
        
        if not transfer.sale_date:
            complete_button = QPushButton("Complete Sale")
            complete_button.clicked.connect(lambda: self.complete_sale(transfer))
            layout.addWidget(complete_button)
        
        return button_widget
    
    def edit_transfer(self, transfer, tx):
        from exchange_transfer_dialog import ExchangeTransferDialog
        dialog = ExchangeTransferDialog(tx.id, self, transfer)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_activity()
    
    def complete_sale(self, transfer):
        from exchange_transfer_dialog import ExchangeTransferDialog
        dialog = ExchangeTransferDialog(transfer.out_transaction_id, self, transfer)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_activity() 