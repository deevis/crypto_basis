from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel, QPushButton, QHBoxLayout
from btc_service import BTCService
from decimal import Decimal

class BTCUTXODialog(QDialog):
    def __init__(self, address, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"UTXOs for {address}")
        self.resize(700, 400)
        self.address = address
        self.btc_service = BTCService(test_connection=True)
        self.setup_ui()
        self.load_utxos()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.info_label = QLabel(f"UTXOs for address: {self.address}")
        layout.addWidget(self.info_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["TXID", "VOUT", "Amount (BTC)", "Block Height"])
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def load_utxos(self):
        utxos, total = self.btc_service.check_address_utxos(self.address)
        self.table.setRowCount(len(utxos))
        for i, utxo in enumerate(utxos):
            self.table.setItem(i, 0, QTableWidgetItem(utxo.get('txid', '')))
            self.table.setItem(i, 1, QTableWidgetItem(str(utxo.get('vout', ''))))
            self.table.setItem(i, 2, QTableWidgetItem(str(utxo.get('amount', ''))))
            # Try to get block height if available
            block_height = ''
            if 'height' in utxo:
                block_height = str(utxo['height'])
            self.table.setItem(i, 3, QTableWidgetItem(block_height))
        self.info_label.setText(f"UTXOs for address: {self.address} | Total: {total} BTC") 