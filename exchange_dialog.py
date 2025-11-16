from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QTableWidget, QTableWidgetItem, QMessageBox, QLineEdit,
                           QCheckBox, QFormLayout)
from PyQt6.QtCore import Qt
from db_config import SessionLocal
from models import Exchange
from datetime import datetime

class AddEditExchangeDialog(QDialog):
    def __init__(self, exchange=None, parent=None):
        super().__init__(parent)
        self.exchange = exchange
        self.session = SessionLocal()
        
        self.setWindowTitle("Add Exchange" if not exchange else "Edit Exchange")
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # Form for exchange details
        form = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.active_check = QCheckBox()
        self.active_check.setChecked(True)
        
        if exchange:
            self.name_edit.setText(exchange.name)
            self.description_edit.setText(exchange.description or "")
            self.active_check.setChecked(exchange.active)
        
        form.addRow("Name:", self.name_edit)
        form.addRow("Description:", self.description_edit)
        form.addRow("Active:", self.active_check)
        
        layout.addLayout(form)
        
        # Buttons
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")
        
        save_button.clicked.connect(self.save_exchange)
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
    
    def save_exchange(self):
        try:
            name = self.name_edit.text().strip()
            if not name:
                raise ValueError("Exchange name is required")
            
            if not self.exchange:
                self.exchange = Exchange()
            
            self.exchange.name = name
            self.exchange.description = self.description_edit.text().strip()
            self.exchange.active = self.active_check.isChecked()
            
            if not self.exchange.id:
                self.session.add(self.exchange)
            
            self.session.commit()
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

class ManageExchangesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = SessionLocal()
        
        self.setWindowTitle("Manage Exchanges")
        self.setModal(True)
        self.setMinimumWidth(600)
        
        layout = QVBoxLayout(self)
        
        # Add Exchange button
        add_button = QPushButton("Add Exchange")
        add_button.clicked.connect(self.add_exchange)
        layout.addWidget(add_button)
        
        # Exchanges table
        self.table = QTableWidget()
        self.setup_table()
        layout.addWidget(self.table)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        
        self.load_exchanges()
    
    def setup_table(self):
        headers = ["Name", "Description", "Active", "Created Date", "Actions"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSortingEnabled(True)
    
    def load_exchanges(self):
        exchanges = self.session.query(Exchange).order_by(Exchange.name).all()
        self.table.setRowCount(len(exchanges))
        
        for i, exchange in enumerate(exchanges):
            # Create button container
            button_widget = QWidget()
            button_layout = QHBoxLayout(button_widget)
            button_layout.setContentsMargins(0, 0, 0, 0)
            
            edit_button = QPushButton("Edit")
            edit_button.clicked.connect(lambda checked, e=exchange: self.edit_exchange(e))
            
            button_layout.addWidget(edit_button)
            
            items = [
                QTableWidgetItem(exchange.name),
                QTableWidgetItem(exchange.description or ""),
                QTableWidgetItem("Yes" if exchange.active else "No"),
                QTableWidgetItem(exchange.created_date.strftime('%Y-%m-%d %H:%M'))
            ]
            
            for col, item in enumerate(items):
                self.table.setItem(i, col, item)
            
            self.table.setCellWidget(i, len(items), button_widget)
        
        self.table.resizeColumnsToContents()
    
    def add_exchange(self):
        dialog = AddEditExchangeDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_exchanges()
    
    def edit_exchange(self, exchange):
        dialog = AddEditExchangeDialog(exchange, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_exchanges() 