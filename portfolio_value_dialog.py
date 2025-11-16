from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                           QCheckBox, QDateEdit, QLabel, QComboBox, QMessageBox)
from PyQt6.QtCore import Qt, QDate
import pyqtgraph as pg
from datetime import datetime, timedelta
from db_config import SessionLocal
from models import Transaction, CoinPrice, OperationType
from sqlalchemy import func, case
import logging

logger = logging.getLogger(__name__)

class PortfolioValueDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Portfolio Value Over Time")
        self.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # Controls
        controls = QHBoxLayout()
        
        # Get earliest transaction date
        session = SessionLocal()
        earliest_tx_date = session.query(func.min(Transaction.operation_date)).scalar()
        
        # Date range
        date_layout = QHBoxLayout()
        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        
        # Set calendar popup and connect date changes
        self.start_date.setCalendarPopup(True)
        self.end_date.setCalendarPopup(True)
        self.start_date.dateChanged.connect(self.update_graph)
        self.end_date.dateChanged.connect(self.update_graph)
        
        # Set initial dates
        if earliest_tx_date:
            self.start_date.setDate(QDate(
                earliest_tx_date.year,
                earliest_tx_date.month,
                earliest_tx_date.day
            ))
        else:
            self.start_date.setDate(QDate.currentDate().addYears(-1))
        self.end_date.setDate(QDate.currentDate())
        
        date_layout.addWidget(QLabel("From:"))
        date_layout.addWidget(self.start_date)
        date_layout.addWidget(QLabel("To:"))
        date_layout.addWidget(self.end_date)
        controls.addLayout(date_layout)
        
        # Aggregation dropdown
        agg_layout = QHBoxLayout()
        agg_layout.addWidget(QLabel("Aggregation:"))
        self.agg_combo = QComboBox()
        self.agg_combo.addItems(["Daily", "Weekly", "Monthly"])
        self.agg_combo.currentTextChanged.connect(self.update_graph)
        agg_layout.addWidget(self.agg_combo)
        controls.addLayout(agg_layout)
        
        # Coin selection
        self.coin_checks = {}
        coin_layout = QHBoxLayout()
        coins = session.query(Transaction.currency_ticker).distinct().all()
        for coin in coins:
            cb = QCheckBox(coin[0])
            # Only check BTC by default
            cb.setChecked(coin[0] == "BTC")
            cb.stateChanged.connect(self.update_graph)
            self.coin_checks[coin[0]] = cb
            coin_layout.addWidget(cb)
        controls.addLayout(coin_layout)
        
        layout.addLayout(controls)
        
        # Graph
        self.graph = pg.PlotWidget()
        self.graph.setBackground('w')
        self.graph.showGrid(x=True, y=True)
        
        # Add second y-axis for coin balance
        self.balance_axis = pg.ViewBox()
        self.graph.scene().addItem(self.balance_axis)
        self.balance_axis.setGeometry(self.graph.plotItem.vb.sceneBoundingRect())
        self.graph.plotItem.getViewBox().sigResized.connect(self._update_balance_axis)
        self.balance_axis.setXLink(self.graph.plotItem)
        
        # Add second axis to the right side
        self.right_axis = pg.AxisItem("right")
        self.graph.plotItem.layout.addItem(self.right_axis, 2, 3)
        self.right_axis.linkToView(self.balance_axis)
        
        layout.addWidget(self.graph)
        
        # Update button
        update_btn = QPushButton("Update")
        update_btn.clicked.connect(self.update_graph)
        layout.addWidget(update_btn)
        
        self.update_graph()
    
    def format_value_axis(self, values):
        """Format values in thousands (k)"""
        # Convert actual dollar values to k
        values_in_k = values / 1000.0
        if values_in_k >= 1000:  # 1M+
            return f"{values_in_k/1000:.0f}M"
        elif values_in_k >= 1:  # 1k+
            return f"{values_in_k:.0f}k"
        elif abs(values) >= 100:  # 100+
            return f"{values:.0f}"
        elif abs(values) > 0:  # >0
            return f"{values:.1f}"
        return "0"

    def get_next_date(self, current_date):
        """Get next date based on aggregation setting"""
        agg = self.agg_combo.currentText()
        if agg == "Daily":
            return current_date + timedelta(days=1)
        elif agg == "Weekly":
            return current_date + timedelta(days=7)
        else:  # Monthly
            # Move to first of next month
            if current_date.month == 12:
                return datetime(current_date.year + 1, 1, 1).date()
            else:
                return datetime(current_date.year, current_date.month + 1, 1).date()

    def get_period_data(self, session, coin, start_date, end_date):
        """Get aggregated data for a period"""
        total_value = 0
        total_balance = 0
        count = 0
        
        current = start_date
        while current <= end_date:
            balance = self.get_balance_at_date(session, coin, current)
            price = session.query(CoinPrice)\
                .filter(CoinPrice.ticker == coin,
                       CoinPrice.price_date == current)\
                .first()
            
            if balance and price:
                total_value += balance * price.price_usd
                total_balance += balance
                count += 1
            
            current += timedelta(days=1)
        
        if count > 0:
            return total_value / count, total_balance / count
        return None, None

    def update_graph(self):
        self.graph.clear()  # Clear existing plots
        self.balance_axis.clear()  # Clear secondary axis
        self.graph.addLegend()
        
        # Reset view boxes
        self.graph.plotItem.getViewBox().setXRange(0, 1)
        self.balance_axis.setXRange(0, 1)
        
        session = SessionLocal()
        start_date = self.start_date.date().toPyDate()
        end_date = self.end_date.date().toPyDate()
        
        # Add logging to debug date range
        logger.debug(f"Updating graph with date range: {start_date} to {end_date}")
        
        # Validate date range
        if start_date > end_date:
            QMessageBox.warning(
                self,
                "Invalid Date Range",
                "Start date must be before end date"
            )
            return
        
        # Get earliest price date to prevent going too far back
        earliest_price = session.query(func.min(CoinPrice.price_date)).scalar()
        if earliest_price and start_date < earliest_price.date():
            QMessageBox.information(
                self,
                "Date Range Adjusted",
                f"Start date adjusted to earliest available price data: {earliest_price.date()}"
            )
            start_date = earliest_price.date()
            self.start_date.setDate(QDate(start_date.year, start_date.month, start_date.day))
        
        # Get selected coins
        selected_coins = [coin for coin, cb in self.coin_checks.items() if cb.isChecked()]
        
        # Calculate daily balances and values for each coin
        for coin in selected_coins:
            timestamps = []
            values = []
            balances = []
            
            current_date = start_date
            while current_date <= end_date:
                if self.agg_combo.currentText() == "Daily":
                    # Use existing daily logic
                    balance = self.get_balance_at_date(session, coin, current_date)
                    price = session.query(CoinPrice)\
                        .filter(CoinPrice.ticker == coin,
                               CoinPrice.price_date == current_date)\
                        .first()
                    
                    if balance and price:
                        timestamp = datetime.combine(current_date, datetime.min.time()).timestamp()
                        timestamps.append(timestamp)
                        values.append(balance * price.price_usd)
                        balances.append(balance)
                else:
                    # Get period end date
                    next_date = self.get_next_date(current_date)
                    period_end = min(next_date - timedelta(days=1), end_date)
                    
                    # Get aggregated data for period
                    avg_value, avg_balance = self.get_period_data(session, coin, current_date, period_end)
                    
                    if avg_value is not None:
                        timestamp = datetime.combine(current_date, datetime.min.time()).timestamp()
                        timestamps.append(timestamp)
                        values.append(avg_value)
                        balances.append(avg_balance)
                
                current_date = self.get_next_date(current_date)
            
            if timestamps and values:
                # Plot value series in green
                value_curve = self.graph.plot(timestamps, values, 
                                            name=f"{coin} Value ($)", 
                                            pen=pg.mkPen(color='g', width=2))
                
                # Plot balance series in blue on second axis
                balance_curve = pg.PlotDataItem(timestamps, balances, 
                                              name=f"{coin} Balance",
                                              pen=pg.mkPen(color='b', width=2))
                self.balance_axis.addItem(balance_curve)
                
                # Add balance curve to legend manually
                self.graph.plotItem.legend.addItem(balance_curve, f"{coin} Balance")
        
        # Custom date axis with adaptive formatting
        class AdaptiveDateAxis(pg.DateAxisItem):
            def tickStrings(self, values, scale, spacing):
                if not values:
                    return []
                
                # Calculate the range in days
                range_days = (max(values) - min(values)) / (24 * 3600)
                
                # Ensure we have reasonable tick spacing
                if range_days <= 7:  # Week or less
                    return [datetime.fromtimestamp(v).strftime('%b %d %H:%M') for v in values]
                elif range_days <= 30:  # Month or less
                    return [datetime.fromtimestamp(v).strftime('%b %d') for v in values]
                elif range_days <= 365:  # Year or less
                    return [datetime.fromtimestamp(v).strftime('%b %d') for v in values]
                elif range_days <= 365 * 2:  # Two years or less
                    return [datetime.fromtimestamp(v).strftime('%b %Y') for v in values]
                else:
                    return [datetime.fromtimestamp(v).strftime('%Y') for v in values]
        
        # Create and set the axis
        axis = AdaptiveDateAxis(orientation='bottom')
        self.graph.setAxisItems({'bottom': axis})
        
        # Enable auto-range after plotting
        self.graph.plotItem.getViewBox().enableAutoRange()
        self.balance_axis.enableAutoRange()
        
        # Format value axis in thousands
        self.graph.getAxis('left').setLabel('Value (USD)')
        self.graph.getAxis('left').setStyle(showValues=True)
        self.graph.getAxis('left').tickFormatter = self.format_value_axis
        
        # Format right axis for coin balance
        self.right_axis.setLabel('Coin Balance')
        
        session.close()
    
    def get_balance_at_date(self, session, coin, date):
        """Calculate balance of a coin at a specific date"""
        balance = session.query(func.sum(case(
            (Transaction.operation_type == OperationType.IN, Transaction.operation_amount),
            (Transaction.operation_type == OperationType.OUT, -Transaction.operation_amount),
            else_=0
        ))).filter(
            Transaction.currency_ticker == coin,
            Transaction.operation_date <= date
        ).scalar() or 0
        
        return balance 

    def _update_balance_axis(self):
        """Update balance axis geometry when graph is resized"""
        self.balance_axis.setGeometry(self.graph.plotItem.vb.sceneBoundingRect()) 