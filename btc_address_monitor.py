from db_config import SessionLocal
from models import BTCAddressMonitoring, BTCAddressUTXO, Transaction
from btc_service import BTCService
from datetime import datetime, timedelta
import logging
from decimal import Decimal
import time
from sqlalchemy import func

logger = logging.getLogger(__name__)

class BTCAddressMonitor:
    def __init__(self):
        self.btc_service = BTCService(test_connection=False)  # Don't test on init
        self.check_interval = 300  # 5 minutes between checks
    
    def start_monitoring(self):
        """Main monitoring loop"""
        logger.info("Starting BTC address monitoring service")
        
        while True:
            try:
                self.check_addresses()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(60)  # Wait a minute before retrying on error
    
    def check_addresses(self):
        """Check all active monitored addresses"""
        # First check if BTC RPC is available
        if not self.btc_service.check_connection():
            logger.warning("Bitcoin Core RPC not available, skipping address checks")
            return
        
        db = SessionLocal()
        try:
            logger.info("Checking for addresses to monitor...")
            
            # Get active addresses that haven't been checked recently
            addresses = db.query(BTCAddressMonitoring).filter(
                BTCAddressMonitoring.monitor_status == 'active',
                (
                    BTCAddressMonitoring.last_check_timestamp.is_(None) |
                    (BTCAddressMonitoring.last_check_timestamp < datetime.utcnow() - timedelta(minutes=5))
                )
            ).all()
            
            logger.info(f"Found {len(addresses)} addresses to check")
            
            # Let's add more debug info to see what's in the database
            total_addresses = db.query(BTCAddressMonitoring).count()
            active_addresses = db.query(BTCAddressMonitoring).filter(
                BTCAddressMonitoring.monitor_status == 'active'
            ).count()
            recently_checked = db.query(BTCAddressMonitoring).filter(
                BTCAddressMonitoring.monitor_status == 'active',
                BTCAddressMonitoring.last_check_timestamp >= datetime.utcnow() - timedelta(minutes=5)
            ).count()
            
            logger.info(f"Database status:")
            logger.info(f"  Total addresses: {total_addresses}")
            logger.info(f"  Active addresses: {active_addresses}")
            logger.info(f"  Recently checked: {recently_checked}")
            
            for addr in addresses:
                try:
                    logger.info(f"Processing address: {addr.bitcoin_address}")
                    logger.info(f"  Source: {addr.source_label}")
                    logger.info(f"  Last check: {addr.last_check_timestamp}")
                    logger.info(f"  Last balance: {addr.last_known_balance}")
                    
                    self.check_single_address(db, addr)
                    
                    # Commit after each successful address check
                    db.commit()
                    logger.info(f"Successfully processed and committed {addr.bitcoin_address}")
                except Exception as e:
                    logger.exception(f"Error checking address {addr.bitcoin_address}")
                    db.rollback()  # Rollback on error
            
            logger.info("Completed address check cycle")
            
        finally:
            db.close()
    
    def check_single_address(self, db, addr):
        """Check a single address for updates"""
        logger.debug(f"Getting blockchain info for {addr.bitcoin_address}")
        
        # Get current blockchain info
        chain_info = self.btc_service._call_rpc("getblockchaininfo")
        current_height = chain_info['blocks']
        logger.debug(f"Current block height: {current_height}")
        
        # Determine start block for scanning
        start_block = None
        if addr.last_block_checked:
            # If we've checked before, start from last checked block
            start_block = addr.last_block_checked
            logger.info(f"Using last checked block {start_block}")
        elif addr.origin_block_number:
            # Start from origin block if known
            start_block = max(0, addr.origin_block_number - 10)  # Start a few blocks earlier to be safe
            logger.info(f"Using origin block {addr.origin_block_number}, starting scan from block {start_block}")
        
        # Get UTXOs directly without using a watch wallet
        utxos, new_balance = self.btc_service.check_address_utxos(addr.bitcoin_address, start_block)
        old_balance = addr.last_known_balance or Decimal('0')
        
        logger.info(f"Balance for {addr.bitcoin_address}:")
        logger.info(f"  Old: {old_balance:.8f} BTC")
        logger.info(f"  New: {new_balance:.8f} BTC")
        logger.info(f"  Change: {(new_balance - old_balance):+.8f} BTC")
        
        # Check for balance change notification
        if addr.notification_threshold:
            change = abs(new_balance - old_balance)
            if change >= addr.notification_threshold:
                logger.info(f"Balance change exceeds notification threshold ({addr.notification_threshold:.8f} BTC)")
                self.notify_balance_change(addr, old_balance, new_balance)
        
        # Update monitored address record
        logger.debug("Updating address record")
        addr.last_known_balance = new_balance
        addr.last_check_timestamp = datetime.utcnow()
        addr.last_block_checked = current_height
        
        # Check if we detected a balance change, which might indicate new transactions
        if new_balance != old_balance:
            logger.info(f"Balance change detected: {old_balance:.8f} -> {new_balance:.8f}")
            
            # Scan blocks from last_block_checked to current_height to find new activity
            if addr.last_block_checked and addr.last_block_checked < current_height:
                scan_start = addr.last_block_checked + 1
                logger.info(f"Scanning blocks {scan_start} to {current_height} for activity")
                
                # Scan each block for transactions involving this address
                for height in range(scan_start, current_height + 1):
                    block_hash = self.btc_service._call_rpc("getblockhash", [height])
                    block = self.btc_service._call_rpc("getblock", [block_hash, 2])
                    
                    for tx in block['tx']:
                        # Simple check for address in outputs
                        for vout in tx['vout']:
                            script_pub_key = vout['scriptPubKey']
                            output_addresses = []
                            
                            # New format (single address)
                            if 'address' in script_pub_key:
                                output_addresses.append(script_pub_key['address'])
                            # Old format (multiple addresses)
                            elif 'addresses' in script_pub_key:
                                output_addresses.extend(script_pub_key['addresses'])
                            
                            if addr.bitcoin_address in output_addresses:
                                # Update transaction info
                                addr.last_transaction_hash = tx['txid']
                                addr.last_activity_block = height
                                logger.info(f"Found new activity in block {height}, tx {tx['txid']}")
                                break
        
        # Process UTXOs
        current_utxos = {f"{u['txid']}:{u['vout']}" for u in utxos}
        
        # Mark spent UTXOs
        logger.debug("Checking for spent UTXOs")
        spent_query = db.query(BTCAddressUTXO).filter(
            BTCAddressUTXO.bitcoin_address == addr.bitcoin_address,
            BTCAddressUTXO.spent_in_tx.is_(None)
        ).filter(
            ~func.concat(BTCAddressUTXO.txid, ':', BTCAddressUTXO.vout).in_(current_utxos)
        )
        
        spent_count = spent_query.count()
        if spent_count > 0:
            logger.info(f"Marking {spent_count} UTXOs as spent")
            spent_query.update({"spent_in_tx": "unknown"}, synchronize_session=False)
        
        # Add new UTXOs
        logger.debug("Processing new UTXOs")
        for utxo in utxos:
            utxo_key = f"{utxo['txid']}:{utxo['vout']}"
            logger.debug(f"Checking UTXO: {utxo_key}")
            
            # Check if UTXO already exists
            existing = db.query(BTCAddressUTXO).filter(
                BTCAddressUTXO.bitcoin_address == addr.bitcoin_address,
                BTCAddressUTXO.txid == utxo['txid'],
                BTCAddressUTXO.vout == utxo['vout']
            ).first()
            
            if not existing:
                logger.info(f"Found new UTXO: {utxo_key}")
                logger.debug(f"UTXO details: {utxo}")
                
                # Get transaction details for block height
                tx_info = self.btc_service.get_raw_transaction_info(utxo['txid'])
                
                # Parse script type from descriptor
                script_type = 'unknown'
                
                # First try to get script type from 'desc' field if available
                desc = utxo.get('desc')
                if desc:
                    if 'pkh(' in desc:
                        script_type = 'p2pkh'
                    elif 'wpkh(' in desc:
                        script_type = 'p2wpkh'
                    elif 'sh(wpkh(' in desc:
                        script_type = 'p2sh'
                    elif 'wsh(' in desc:
                        script_type = 'p2wsh'
                    elif 'tr(' in desc:
                        script_type = 'p2tr'
                    logger.debug(f"Detected script type from descriptor: {script_type} ({desc})")
                else:
                    # Fallback: determine script type from address format
                    address = addr.bitcoin_address
                    if address.startswith('1'):
                        script_type = 'p2pkh'
                    elif address.startswith('3'):
                        script_type = 'p2sh'
                    elif address.startswith('bc1q'):
                        script_type = 'p2wpkh'
                    elif address.startswith('bc1p'):
                        script_type = 'p2tr'
                    elif address.startswith('bc1') and len(address) > 42:
                        script_type = 'p2wsh'
                    logger.debug(f"Detected script type from address format: {script_type}")
                
                new_utxo = BTCAddressUTXO(
                    bitcoin_address=addr.bitcoin_address,
                    txid=utxo['txid'],
                    vout=utxo['vout'],
                    amount=Decimal(str(utxo['amount'])),
                    script_type=script_type,  # Use properly parsed script type
                    block_height=tx_info.get('block_number', 0),
                    spent_in_tx=None
                )
                db.add(new_utxo)
                logger.info(f"Added new UTXO: {utxo_key} ({new_utxo.amount:.8f} BTC)")
                
                # Update last_transaction_hash and last_activity_block if this is newer
                if tx_info.get('block_number'):
                    block_height = tx_info.get('block_number')
                    if addr.last_activity_block is None or block_height > addr.last_activity_block:
                        addr.last_activity_block = block_height
                        addr.last_transaction_hash = utxo['txid']
                        logger.info(f"Updated last activity to block {block_height}, tx {utxo['txid']}")
    
    def notify_balance_change(self, addr, old_balance, new_balance):
        """Handle balance change notification"""
        change = new_balance - old_balance
        logger.info(f"Balance change for {addr.bitcoin_address}: {change:+.8f} BTC")
        # TODO: Implement actual notification system (email, UI notification, etc.) 