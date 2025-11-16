from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                           QTextBrowser, QTabWidget)
from PyQt6.QtCore import Qt
from datetime import datetime

class TransactionDetailsDialog(QDialog):
    def __init__(self, tx_data, address=None, parent=None):
        super().__init__(parent)
        self.tx_data = tx_data
        self.address = address  # Can be None for general viewing
        
        self.setWindowTitle(f"Transaction Details - {tx_data['txid']}")
        self.setModal(True)
        self.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # Create tab widget
        tabs = QTabWidget()
        
        # Summary tab
        summary_widget = QTextBrowser()
        summary_widget.setOpenExternalLinks(True)
        summary_html = self.format_summary()
        summary_widget.setHtml(summary_html)
        tabs.addTab(summary_widget, "Summary")
        
        # Inputs tab
        inputs_widget = QTextBrowser()
        inputs_html = self.format_inputs()
        inputs_widget.setHtml(inputs_html)
        tabs.addTab(inputs_widget, "Inputs")
        
        # Outputs tab
        outputs_widget = QTextBrowser()
        outputs_html = self.format_outputs()
        outputs_widget.setHtml(outputs_html)
        tabs.addTab(outputs_widget, "Outputs")
        
        layout.addWidget(tabs)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        force_button = QPushButton("Force Accept")
        force_button.clicked.connect(self.accept)
        force_button.setToolTip("Use this transaction anyway")
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        # Remove force accept button if just viewing
        if not address:
            force_button.hide()
        
        button_layout.addWidget(force_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
    
    def format_summary(self):
        """Format transaction summary as HTML"""
        return f"""
        <h2>Transaction Details</h2>
        <p><b>Transaction ID:</b> {self.tx_data['txid']}</p>
        <p><b>Block Hash:</b> {self.tx_data['blockhash']}</p>
        <p><b>Block Time:</b> {datetime.fromtimestamp(self.tx_data['time']).strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><b>Size:</b> {self.tx_data['size']} bytes</p>
        <p><b>Version:</b> {self.tx_data['version']}</p>
        <p><b>Looking for address:</b> <span style="color: red">{self.address}</span></p>
        <p><b>Total Inputs:</b> {len(self.tx_data['vin'])}</p>
        <p><b>Total Outputs:</b> {len(self.tx_data['vout'])}</p>
        <p><a href="https://mempool.space/tx/{self.tx_data['txid']}">View on Block Explorer</a></p>
        """
    
    def format_inputs(self):
        """Format transaction inputs as HTML"""
        html = "<h2>Transaction Inputs</h2>"
        for i, vin in enumerate(self.tx_data['vin'], 1):
            html += f"""
            <h3>Input #{i}</h3>
            <p><b>Previous TX:</b> {vin.get('txid', 'Coinbase')}</p>
            <p><b>Output Index:</b> {vin.get('vout', 'N/A')}</p>
            <p><b>Script Sig:</b> {vin.get('scriptSig', {}).get('hex', 'N/A')}</p>
            <hr>
            """
        return html
    
    def format_outputs(self):
        """Format transaction outputs as HTML with highlighting"""
        html = "<h2>Transaction Outputs</h2>"
        for i, vout in enumerate(self.tx_data['vout'], 1):
            script_pub_key = vout['scriptPubKey']
            addresses = []
            
            if 'address' in script_pub_key:
                addresses.append(script_pub_key['address'])
            elif 'addresses' in script_pub_key:
                addresses.extend(script_pub_key['addresses'])
            
            # Only highlight if we're looking for a specific address
            style = ''
            if self.address and self.address in addresses:
                style = 'background-color: #ffe6e6;'
            
            html += f"""
            <div style="{style}">
            <h3>Output #{i}</h3>
            <p><b>Amount:</b> {vout['value']} BTC</p>
            <p><b>Type:</b> {script_pub_key.get('type', 'Unknown')}</p>
            <p><b>Addresses:</b></p>
            <ul>
            """
            
            if addresses:
                for addr in addresses:
                    color = 'red' if addr == self.address else 'black'
                    html += f'<li style="color: {color}">{addr}</li>'
            else:
                html += '<li>No address available (raw script output)</li>'
            
            html += f"""
            </ul>
            <p><b>Script:</b> {script_pub_key.get('hex', 'N/A')}</p>
            <hr>
            </div>
            """
        return html 