import logging
import sys
from btc_address_monitor import BTCAddressMonitor
from datetime import datetime

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'btc_monitor_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)

logger = logging.getLogger(__name__)

def main():
    try:
        logger.info("Starting BTC address monitoring service")
        logger.info("Initializing monitor...")
        
        monitor = BTCAddressMonitor()
        
        logger.info("Monitor initialized, starting monitoring loop")
        monitor.start_monitoring()
        
    except KeyboardInterrupt:
        logger.info("Received shutdown signal, stopping monitor")
    except Exception as e:
        logger.exception("Fatal error in monitoring service")
        sys.exit(1)

if __name__ == "__main__":
    main() 