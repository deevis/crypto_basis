import sys
import os
import threading
from dotenv import load_dotenv
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow
from db_config import init_db, transactions_populated
from data_importer import import_csv
from price_service import PriceService
from btc_address_monitor import BTCAddressMonitor

def warm_price_cache():
    """Initialize price cache in background thread"""
    price_service = PriceService()
    price_service.warm_cache()

def main():
    # Load environment variables
    load_dotenv()
    
    # Initialize database
    init_db()
    already_populated = transactions_populated()
    
    # Start price cache warming in background
    cache_thread = threading.Thread(target=warm_price_cache)
    cache_thread.daemon = True
    cache_thread.start()
    
    # Start BTC address monitoring in background thread
    # Initialize without testing connection to avoid startup delays
    monitor = BTCAddressMonitor()
    monitor_thread = threading.Thread(target=monitor.start_monitoring, daemon=True)
    monitor_thread.start()
    
    # only automatically import if the transactions table is empty
    # if not, the user can manually import
    if not already_populated:   
        csv_path = os.getenv("CSV_IMPORT_PATH")
        if csv_path and os.path.exists(csv_path):
            import_csv(csv_path)
        else:
            print(f"Warning: CSV file not found at {csv_path}")
    
    # Start GUI application
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 