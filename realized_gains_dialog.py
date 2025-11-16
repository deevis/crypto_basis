from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QTableWidget, QTableWidgetItem, QComboBox, QFormLayout)
from PyQt6.QtCore import Qt
from db_config import SessionLocal
from models import ExchangeTransfer, Transaction, CapitalGainsTerm
from sqlalchemy import extract, func
from datetime import datetime, timedelta

class RealizedGainsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = SessionLocal()
        
        self.setWindowTitle("Realized Gains")
        self.setModal(True)
        self.setMinimumWidth(1000)
        self.setMinimumHeight(600)
        
        layout = QVBoxLayout(self)
        
        # Year selection
        form_layout = QFormLayout()
        self.year_combo = QComboBox()
        self.load_available_years()
        self.year_combo.currentIndexChanged.connect(self.load_gains)
        form_layout.addRow("Tax Year:", self.year_combo)
        layout.addLayout(form_layout)
        
        # Summary section
        summary_layout = QHBoxLayout()
        self.total_gains_label = QLabel()
        self.total_proceeds_label = QLabel()
        self.total_cost_basis_label = QLabel()
        summary_layout.addWidget(self.total_gains_label)
        summary_layout.addWidget(self.total_proceeds_label)
        summary_layout.addWidget(self.total_cost_basis_label)
        layout.addLayout(summary_layout)
        
        # Gains table
        self.table = QTableWidget()
        self.setup_table()
        layout.addWidget(self.table)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        
        # Load initial data
        self.load_gains()
    
    def setup_table(self):
        headers = ["Sale Date", "Exchange", "Currency", "Amount", "Acquisition Date",
                  "Acquisition Price", "Sale Price", "Proceeds", "Cost Basis", 
                  "Realized Gain", "Term", "Wallet"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSortingEnabled(True)
    
    def load_available_years(self):
        years = self.session.query(
            extract('year', ExchangeTransfer.sale_date).label('year')
        ).filter(
            ExchangeTransfer.sale_date.isnot(None)
        ).distinct().order_by('year').all()
        
        self.year_combo.clear()
        self.year_combo.addItem("All Years", None)  # Add "All Years" option
        
        for year in years:
            self.year_combo.addItem(str(year[0]), year[0])
        
        # Add current year if not in list
        current_year = datetime.now().year
        if not any(year[0] == current_year for year in years):
            self.year_combo.addItem(str(current_year), current_year)
    
    def load_gains(self):
        selected_year = self.year_combo.currentData()
        
        # Base query
        query = self.session.query(
            ExchangeTransfer,
            Transaction
        ).join(
            Transaction,
            ExchangeTransfer.out_transaction_id == Transaction.id
        ).filter(
            ExchangeTransfer.sale_date.isnot(None)
        )
        
        # Apply year filter if selected
        if selected_year is not None:
            query = query.filter(extract('year', ExchangeTransfer.sale_date) == selected_year)
        
        transfers = query.order_by(ExchangeTransfer.sale_date).all()
        
        self.table.setRowCount(len(transfers))
        
        total_gains = 0
        total_proceeds = 0
        total_cost_basis = 0
        total_long_term_gains = 0
        total_short_term_gains = 0
        
        for i, (transfer, tx) in enumerate(transfers):
            proceeds = transfer.sale_amount * transfer.sale_price
            cost_basis = transfer.sale_amount * transfer.acquisition_price if transfer.acquisition_price else 0
            
            items = [
                QTableWidgetItem(transfer.sale_date.strftime('%Y-%m-%d')),
                QTableWidgetItem(transfer.exchange.name),
                QTableWidgetItem(tx.currency_ticker),
                QTableWidgetItem(f"{transfer.sale_amount:.8f}"),
                QTableWidgetItem(transfer.acquisition_date.strftime('%Y-%m-%d') if transfer.acquisition_date else ""),
                QTableWidgetItem(f"${transfer.acquisition_price:,.2f}" if transfer.acquisition_price else ""),
                QTableWidgetItem(f"${transfer.sale_price:,.2f}"),
                QTableWidgetItem(f"${proceeds:,.2f}"),
                QTableWidgetItem(f"${cost_basis:,.2f}"),
                QTableWidgetItem(f"${transfer.realized_gain:,.2f}"),
                QTableWidgetItem("Long Term" if transfer.term_type == CapitalGainsTerm.LONG else "Short Term"),
                QTableWidgetItem(tx.wallet_name)
            ]
            
            for col, item in enumerate(items):
                self.table.setItem(i, col, item)
                # Right-align numeric columns
                if col in [3, 4, 5, 6, 7]:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
            
            total_gains += transfer.realized_gain
            total_proceeds += proceeds
            total_cost_basis += cost_basis
            
            # Use stored term_type for totals
            if transfer.term_type == CapitalGainsTerm.LONG:
                total_long_term_gains += transfer.realized_gain
            else:
                total_short_term_gains += transfer.realized_gain
        
        # Update summary labels with more detail
        summary_text = (
            f"Total Gains: ${total_gains:,.2f} "
            f"(Long: ${total_long_term_gains:,.2f}, Short: ${total_short_term_gains:,.2f})"
        )
        self.total_gains_label.setText(summary_text)
        self.total_proceeds_label.setText(f"Total Proceeds: ${total_proceeds:,.2f}")
        self.total_cost_basis_label.setText(f"Total Cost Basis: ${total_cost_basis:,.2f}")
        
        self.table.resizeColumnsToContents() 