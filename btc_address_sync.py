import logging
import os
import sys
from decimal import Decimal
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import time
from db_config import SessionLocal
from btc_service import BTCService
from models import BTCAddressMonitoring

# Configure logging - CHANGED: Set different levels for different loggers
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Suppress verbose HTTP and RPC logs
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("btc_service").setLevel(logging.WARNING)

# Helper function to format balance
def format_btc(amount):
    if amount is None:
        return "0.00000000"
    return f"{float(amount):.8f}"

# Helper function to format time
def format_time(seconds):
    """Format seconds into hours, minutes, seconds"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes)}m {int(seconds)}s"
    else:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"

# Helper function to display progress bar
def progress_bar(current, total, width=50, eta=None, blocks_per_sec=None):
    progress = min(1.0, current / total)
    bar_width = int(width * progress)
    bar = '█' * bar_width + '░' * (width - bar_width)
    percent = int(progress * 100)
    
    result = f"[{bar}] {percent}% ({current}/{total})"
    
    if blocks_per_sec is not None and blocks_per_sec > 0:
        result += f" | {blocks_per_sec:.2f} blocks/sec"
    
    if eta is not None:
        result += f" | ETA: {format_time(eta)}"
        
    return result

class BTCAddressSynchronizer:
    def __init__(self):
        self.btc_service = BTCService(test_connection=True)
        self.db = SessionLocal()
        
        # Exit if BTC service is not available
        if not self.btc_service.is_available:
            logger.error("Bitcoin Core RPC not available. Exiting.")
            sys.exit(1)
            
        # Ensure BTC wallet is loaded
        try:
            self.btc_service.load_watch_wallet()
        except Exception as e:
            logger.error(f"Error loading wallet: {e}")
            sys.exit(1)
    
    def scan_address_activity(self, address, start_block, end_block):
        """Scan for all transactions involving this address between start_block and end_block"""
        print(f"\n📊 Scanning address: {address}")
        print(f"   From block {start_block} to {end_block} ({end_block - start_block + 1} blocks)")
        
        transactions = []
        found_blocks = set()
        total_blocks = end_block - start_block + 1
        
        # Timing variables
        last_progress_update = time.time()
        scan_start_time = time.time()
        block_times = []
        last_block_start_time = scan_start_time
        
        for height in range(start_block, end_block + 1):
            # Track time for this block
            block_start_time = time.time()
            
            # Process the block (existing code)
            try:
                block_hash = self.btc_service._call_rpc("getblockhash", [height])
                block = self.btc_service._call_rpc("getblock", [block_hash, 2])
                
                # Check each transaction in the block
                block_txs_found = 0
                for tx in block['tx']:
                    # Check transaction outputs
                    found = False
                    amount = 0
                    
                    for vout in tx['vout']:
                        script_pub_key = vout['scriptPubKey']
                        output_addresses = []
                        
                        # New format (single address)
                        if 'address' in script_pub_key:
                            output_addresses.append(script_pub_key['address'])
                        # Old format (multiple addresses)
                        elif 'addresses' in script_pub_key:
                            output_addresses.extend(script_pub_key['addresses'])
                        
                        if address in output_addresses:
                            found = True
                            amount = vout['value']
                            transactions.append({
                                'txid': tx['txid'],
                                'block_height': height,
                                'amount': amount,
                                'time': datetime.fromtimestamp(block['time']),
                                'direction': 'in'
                            })
                            block_txs_found += 1
                            found_blocks.add(height)
                            # Print transaction found
                            tx_date = datetime.fromtimestamp(block['time']).strftime('%Y-%m-%d %H:%M:%S')
                            print(f"\n   ✅ Found IN tx: {tx['txid'][:8]}... @ Block {height} ({tx_date}) Amount: +{amount:.8f} BTC")
                            break
                    
                    # If not found in outputs, check inputs
                    if not found:
                        for vin in tx.get('vin', []):
                            if 'txid' in vin and 'vout' in vin:
                                # Get the previous transaction
                                prev_tx = self.btc_service._call_rpc("getrawtransaction", [vin['txid'], True])
                                if 'vout' in prev_tx and len(prev_tx['vout']) > vin['vout']:
                                    prev_vout = prev_tx['vout'][vin['vout']]
                                    script_pub_key = prev_vout['scriptPubKey']
                                    output_addresses = []
                                    
                                    # New format (single address)
                                    if 'address' in script_pub_key:
                                        output_addresses.append(script_pub_key['address'])
                                    # Old format (multiple addresses)
                                    elif 'addresses' in script_pub_key:
                                        output_addresses.extend(script_pub_key['addresses'])
                                    
                                    if address in output_addresses:
                                        amount = prev_vout['value']
                                        transactions.append({
                                            'txid': tx['txid'],
                                            'block_height': height,
                                            'amount': -amount,  # Negative for outgoing
                                            'time': datetime.fromtimestamp(block['time']),
                                            'direction': 'out'
                                        })
                                        block_txs_found += 1
                                        found_blocks.add(height)
                                        # Print transaction found
                                        tx_date = datetime.fromtimestamp(block['time']).strftime('%Y-%m-%d %H:%M:%S')
                                        print(f"\n   ⬆️ Found OUT tx: {tx['txid'][:8]}... @ Block {height} ({tx_date}) Amount: -{amount:.8f} BTC")
                                        break
            except Exception as e:
                print(f"\n   ❌ Error scanning block {height}: {e}")
            
            # Calculate block processing time
            block_end_time = time.time()
            block_time = block_end_time - block_start_time
            block_times.append(block_time)
            
            # Calculate average time per block and estimated time remaining
            blocks_done = height - start_block + 1
            blocks_remaining = end_block - height
            
            # Calculate rolling average (last 50 blocks or all if fewer)
            recent_blocks = block_times[-50:] if len(block_times) > 50 else block_times
            avg_time_per_block = sum(recent_blocks) / len(recent_blocks)
            blocks_per_second = 1.0 / avg_time_per_block if avg_time_per_block > 0 else 0
            eta = blocks_remaining * avg_time_per_block
            
            # Update progress every second or every 10 blocks
            current_time = time.time()
            if height % 10 == 0 or current_time - last_progress_update >= 1:
                progress = progress_bar(blocks_done, total_blocks, eta=eta, blocks_per_sec=blocks_per_second)
                elapsed = current_time - scan_start_time
                print(f"\r   {progress} | Elapsed: {format_time(elapsed)}", end="", flush=True)
                last_progress_update = current_time
        
        # Final stats
        total_time = time.time() - scan_start_time
        blocks_per_second = total_blocks / total_time if total_time > 0 else 0
        
        # Print final progress
        print(f"\r   {progress_bar(total_blocks, total_blocks)} | Total time: {format_time(total_time)} | Avg: {blocks_per_second:.2f} blocks/sec")
        
        # Print summary
        in_txs = [tx for tx in transactions if tx.get('direction') == 'in']
        out_txs = [tx for tx in transactions if tx.get('direction') == 'out']
        in_total = sum(tx['amount'] for tx in in_txs)
        out_total = sum(tx['amount'] for tx in out_txs)
        
        print(f"\n   📝 Summary for {address}:")
        print(f"     • Transactions: {len(transactions)} found in {len(found_blocks)} blocks")
        print(f"     • Incoming: {len(in_txs)} transactions, total: +{in_total:.8f} BTC")
        print(f"     • Outgoing: {len(out_txs)} transactions, total: {out_total:.8f} BTC")
        print(f"     • Net: {(in_total + out_total):.8f} BTC")
        print(f"     • Scan speed: {blocks_per_second:.2f} blocks/sec ({format_time(total_time)} for {total_blocks} blocks)")
        
        return transactions
    
    def sync_address(self, addr):
        """Synchronize a single address"""
        print(f"\n{'='*80}")
        print(f"🔄 Processing: {addr.bitcoin_address}")
        print(f"   Source: {addr.source_label}")
        print(f"   Status: {addr.monitor_status}")
        print(f"   Previous balance: {format_btc(addr.last_known_balance)} BTC")
        print(f"{'='*80}")
        
        # Skip if no origin block is specified
        if addr.origin_block_number is None:
            print(f"⚠️ No origin block for {addr.bitcoin_address}, skipping")
            return
        
        # Use last_block_checked if available, otherwise current chain tip
        end_block = addr.last_block_checked
        if end_block is None:
            chain_info = self.btc_service._call_rpc("getblockchaininfo")
            end_block = chain_info['blocks']
            print(f"📌 No last_block_checked, using current chain tip: {end_block}")
        
        # Scan for activity between origin_block and last_block_checked
        txs = self.scan_address_activity(addr.bitcoin_address, addr.origin_block_number, end_block)
        
        # Update last_transaction_hash and last_activity_block if activity found
        if txs:
            # Sort by block height descending to get the most recent tx
            txs.sort(key=lambda x: x['block_height'], reverse=True)
            latest_tx = txs[0]
            
            addr.last_transaction_hash = latest_tx['txid']
            addr.last_activity_block = latest_tx['block_height']
            print(f"\n✅ Updated last activity: block {addr.last_activity_block}, tx {addr.last_transaction_hash}")
        else:
            print(f"\n⚠️ No activity found for {addr.bitcoin_address}")
            addr.last_transaction_hash = None
            addr.last_activity_block = None
        
        # Get current balance
        print(f"\n💰 Checking current UTXOs...")
        utxos, total_balance = self.btc_service.check_address_utxos(addr.bitcoin_address)
        
        # Set or update the last_known_balance
        old_balance = addr.last_known_balance or Decimal('0')
        addr.last_known_balance = total_balance
        
        print(f"   Balance: {format_btc(old_balance)} BTC → {format_btc(total_balance)} BTC")
        if total_balance != old_balance:
            print(f"   Change: {format_btc(total_balance - old_balance)} BTC")
        
        # Make sure last_check_timestamp and last_block_checked are set
        addr.last_check_timestamp = datetime.utcnow()
        addr.last_block_checked = end_block
        
        # Save the changes
        self.db.commit()
        print(f"\n✅ Successfully synced {addr.bitcoin_address}")
    
    def sync_all_addresses(self):
        """Synchronize all addresses in the database"""
        try:
            # Get all addresses
            addresses = self.db.query(BTCAddressMonitoring).all()
            total_addresses = len(addresses)
            
            print(f"\n{'='*80}")
            print(f"🔍 Starting Bitcoin address synchronization")
            print(f"📊 Found {total_addresses} addresses to sync")
            print(f"{'='*80}\n")
            
            start_time = time.time()
            
            for i, addr in enumerate(addresses):
                # Print header for each address with progress
                print(f"\n{'='*80}")
                print(f"🔄 Address {i+1}/{total_addresses} ({((i+1)/total_addresses)*100:.1f}%)")
                try:
                    self.sync_address(addr)
                except Exception as e:
                    print(f"\n❌ Error syncing address {addr.bitcoin_address}: {e}")
                    self.db.rollback()
            
            elapsed_time = time.time() - start_time
            minutes, seconds = divmod(elapsed_time, 60)
            hours, minutes = divmod(minutes, 60)
            
            print(f"\n{'='*80}")
            print(f"✅ Address synchronization completed")
            print(f"⏱️ Total time: {int(hours)}h {int(minutes)}m {int(seconds)}s")
            print(f"📊 Processed {total_addresses} addresses")
            print(f"{'='*80}")
        finally:
            self.db.close()

if __name__ == "__main__":
    logger.info("Starting BTC address synchronization")
    synchronizer = BTCAddressSynchronizer()
    synchronizer.sync_all_addresses()
    logger.info("Synchronization complete") 