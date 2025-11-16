from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
                           QLabel, QPushButton, QHeaderView, QHBoxLayout, QFrame)
from PyQt6.QtCore import Qt
from db_config import get_db
from models import Transaction, OperationType
from sqlalchemy import func, case
from price_service import PriceService

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            # Strip currency symbols, commas, and percentage signs, then convert to float
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

class TotalsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Coin Totals")
        self.setModal(True)
        self.setMinimumWidth(1200)  # Increased for new column
        self.setMinimumHeight(600)  # Increased for summary section
        
        layout = QVBoxLayout(self)
        
        # Add summary section
        summary_layout = QHBoxLayout()
        
        # Create summary labels with titles
        self.total_cost_label = self.create_summary_label("Total Cost:", "$0.00")
        self.total_value_label = self.create_summary_label("Total Value:", "$0.00")
        self.total_gain_label = self.create_summary_label("Total Gain/Loss:", "0.00%")
        
        summary_layout.addWidget(self.total_cost_label)
        summary_layout.addWidget(self.total_value_label)
        summary_layout.addWidget(self.total_gain_label)
        
        layout.addLayout(summary_layout)
        
        # Add separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)
        
        # Create table
        self.table = QTableWidget()
        self.table.setColumnCount(8)  # Added column for percentage gain
        self.table.setHorizontalHeaderLabels([
            "Coin", "Total Amount", "Avg Cost Basis", 
            "Current Price", "Total Cost Basis", "Current Value",
            "Total Profit", "Percent Gain"
        ])
        
        # Set column stretch
        header = self.table.horizontalHeader()
        for i in range(8):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        
        # Enable sorting
        self.table.setSortingEnabled(True)
        
        layout.addWidget(self.table)
        
        # Add close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        
        # Load data
        self.load_data()
    
    def create_summary_label(self, title, initial_value):
        """Create a formatted summary label with title and value"""
        container = QFrame()
        container.setFrameShape(QFrame.Shape.Box)
        container.setStyleSheet("QFrame { padding: 10px; margin: 5px; }")
        
        layout = QVBoxLayout(container)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(title_label)
        
        value_label = QLabel(initial_value)
        value_label.setStyleSheet("font-size: 16px;")
        value_label.setObjectName("value_label")  # Add object name for finding later
        layout.addWidget(value_label)
        
        return container
        
    def load_data(self):
        db = next(get_db())
        
        # Get aggregated data by coin
        results = db.query(
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
            ).label('total_cost_basis')
        ).group_by(
            Transaction.currency_ticker
        ).all()
        
        # Get current prices
        price_service = PriceService()
        coins = [r[0] for r in results]
        current_prices = price_service.get_current_prices(coins)
        
        # Temporarily disable sorting while populating
        self.table.setSortingEnabled(False)
        
        # Track totals for summary
        total_cost_basis = 0
        total_current_value = 0
        
        # Populate table
        self.table.setRowCount(len(results))
        
        for i, row in enumerate(results):
            coin, total_in, total_out, total_cost_basis_sum = row
            total_in = total_in or 0
            total_out = total_out or 0
            total_cost_basis_sum = total_cost_basis_sum or 0
            
            # Calculate totals
            balance = total_in - total_out
            avg_cost_basis = (total_cost_basis_sum / total_in) if total_in > 0 else 0
            current_price = current_prices.get(coin, 0)
            total_cost_basis_value = balance * avg_cost_basis
            current_value = balance * current_price
            total_profit = current_value - total_cost_basis_value
            
            # Calculate percentage gain/loss
            percent_gain = ((current_value / total_cost_basis_value) - 1) * 100 if total_cost_basis_value > 0 else 0
            
            # Update summary totals
            total_cost_basis += total_cost_basis_value
            total_current_value += current_value
            
            # Create row items with appropriate types for sorting
            items = [
                QTableWidgetItem(coin),
                NumericTableWidgetItem(f"{balance:.8f}"),
                NumericTableWidgetItem(f"${avg_cost_basis:,.2f}"),
                NumericTableWidgetItem(f"${current_price:,.2f}"),
                NumericTableWidgetItem(f"${total_cost_basis_value:,.2f}"),
                NumericTableWidgetItem(f"${current_value:,.2f}"),
                NumericTableWidgetItem(f"${total_profit:,.2f}"),
                PercentageTableWidgetItem(f"{percent_gain:.2f}%")
            ]
            
            # Add items to table
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight if col > 0 else Qt.AlignmentFlag.AlignLeft)
                # Color profit/loss cells based on value
                if col in [6, 7]:  # Total Profit and Percent Gain columns
                    if (col == 6 and total_profit > 0) or (col == 7 and percent_gain > 0):
                        item.setForeground(Qt.GlobalColor.darkGreen)
                    elif (col == 6 and total_profit < 0) or (col == 7 and percent_gain < 0):
                        item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(i, col, item)
        
        # Update summary labels
        total_percent_gain = ((total_current_value / total_cost_basis) - 1) * 100 if total_cost_basis > 0 else 0
        
        # Find value labels by object name
        self.total_cost_label.findChild(QLabel, "value_label").setText(f"${total_cost_basis:,.2f}")
        self.total_value_label.findChild(QLabel, "value_label").setText(f"${total_current_value:,.2f}")
        
        gain_label = self.total_gain_label.findChild(QLabel, "value_label")
        gain_label.setText(f"{total_percent_gain:,.2f}%")
        gain_label.setStyleSheet(
            "font-size: 16px; color: " + 
            ("darkgreen" if total_percent_gain > 0 else "red" if total_percent_gain < 0 else "black")
        )
        
        # Re-enable sorting
        self.table.setSortingEnabled(True)
        
        # Sort by Total Profit (column 6) in descending order
        self.table.sortItems(6, Qt.SortOrder.DescendingOrder) 