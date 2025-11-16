from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QTableWidget, QTableWidgetItem, QMessageBox, QTabWidget,
                           QWidget)
from PyQt6.QtCore import Qt, pyqtSignal
from db_config import SessionLocal
from models import Exchange
from exchange_dialog import AddEditExchangeDialog

class SettingsDialog(QDialog):
    exchanges_updated = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = SessionLocal()
        
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        
        layout = QVBoxLayout(self)
        
        # Create tab widget
        tab_widget = QTabWidget()
        
        # Exchanges tab
        exchanges_tab = QWidget()
        exchanges_layout = QVBoxLayout(exchanges_tab)
        
        # Add Exchange button
        add_button = QPushButton("Add Exchange")
        add_button.clicked.connect(self.add_exchange)
        exchanges_layout.addWidget(add_button)
        
        # Exchanges table
        self.exchanges_table = QTableWidget()
        self.setup_exchanges_table()
        exchanges_layout.addWidget(self.exchanges_table)
        
        tab_widget.addTab(exchanges_tab, "Exchanges")
        
        # Add tab widget to main layout
        layout.addWidget(tab_widget)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        
        # Load data
        self.load_exchanges()
    
    def setup_exchanges_table(self):
        headers = ["Name", "Description", "Active", "Created Date", "Actions"]
        self.exchanges_table.setColumnCount(len(headers))
        self.exchanges_table.setHorizontalHeaderLabels(headers)
        self.exchanges_table.setSortingEnabled(True)
        self.exchanges_table.horizontalHeader().setStretchLastSection(True)
    
    def load_exchanges(self):
        exchanges = self.session.query(Exchange).order_by(Exchange.name).all()
        self.exchanges_table.setRowCount(len(exchanges))
        
        for i, exchange in enumerate(exchanges):
            # Create button container
            button_widget = QWidget()
            button_layout = QHBoxLayout(button_widget)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(2)
            
            edit_button = QPushButton("Edit")
            delete_button = QPushButton("Delete")
            
            edit_button.clicked.connect(lambda checked, e=exchange: self.edit_exchange(e))
            delete_button.clicked.connect(lambda checked, e=exchange: self.delete_exchange(e))
            
            button_layout.addWidget(edit_button)
            button_layout.addWidget(delete_button)
            
            items = [
                QTableWidgetItem(exchange.name),
                QTableWidgetItem(exchange.description or ""),
                QTableWidgetItem("Yes" if exchange.active else "No"),
                QTableWidgetItem(exchange.created_date.strftime('%Y-%m-%d %H:%M'))
            ]
            
            for col, item in enumerate(items):
                self.exchanges_table.setItem(i, col, item)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Make read-only
            
            self.exchanges_table.setCellWidget(i, len(items), button_widget)
        
        self.exchanges_table.resizeColumnsToContents()
    
    def add_exchange(self):
        dialog = AddEditExchangeDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_exchanges()
            self.exchanges_updated.emit()
    
    def edit_exchange(self, exchange):
        dialog = AddEditExchangeDialog(exchange, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_exchanges()
            self.exchanges_updated.emit()
    
    def delete_exchange(self, exchange):
        # Check if exchange is in use
        if hasattr(exchange, 'exchange_transfers') and len(exchange.exchange_transfers) > 0:
            QMessageBox.warning(
                self,
                "Cannot Delete",
                "This exchange has associated transfers and cannot be deleted.\n"
                "You can mark it as inactive instead."
            )
            return
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(f"Are you sure you want to delete the exchange '{exchange.name}'?")
        msg.setWindowTitle("Confirm Delete")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if msg.exec() == QMessageBox.StandardButton.Yes:
            try:
                self.session.delete(exchange)
                self.session.commit()
                self.load_exchanges()
                self.exchanges_updated.emit()
            except Exception as e:
                self.session.rollback()
                QMessageBox.critical(self, "Error", f"Failed to delete exchange: {str(e)}") 