#!/usr/bin/env python3
import time
import logging
import json
import urllib.parse
from datetime import datetime
from decimal import Decimal
from btc_service import BTCService
from db_config import SessionLocal
from models import BTCAddressMonitoring

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def format_btc(amount):
    """Format BTC amount with 8 decimal places"""
    if amount is None:
        return "0.00000000"
    return f"{float(amount):.8f}"

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

def verify_address_import(address):
    """
    Verify that an address was properly imported and check transaction history
    """
    print(f"\n{'='*80}")
    print(f"🔍 Verifying address import: {address}")
    print(f"{'='*80}")
    
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("❌ Bitcoin Core RPC not available. Exiting.")
        return False
    
    try:
        # Try to load wallet
        try:
            btc_service.load_watch_wallet()
            print("✅ Watch wallet loaded")
        except Exception as e:
            error_text = str(e)
            if "is already loaded" in error_text:
                print("✅ Wallet is already loaded - continuing")
            else:
                # Re-raise for any other errors
                raise
        
        # Get wallet info
        wallet_path = btc_service.wallet_path
        print(f"📂 Using wallet: {wallet_path}")
        
        # Check if address is properly imported
        address_info = btc_service._call_rpc("getaddressinfo", [address])
        
        if not address_info:
            print(f"❌ Address not found in wallet")
            return False
            
        # Check if watch-only
        if address_info.get('iswatchonly', False):
            print(f"✅ Address is properly imported as watch-only")
        else:
            print(f"⚠️ Warning: Address is not showing as watch-only. This is unexpected.")
        
        # Get transactions
        received = btc_service._call_rpc("listreceivedbyaddress", [0, True, True, address])
        
        if received and len(received) > 0:
            addr_info = received[0]
            txids = addr_info.get('txids', [])
            
            print(f"\n📝 Address Summary:")
            print(f"   • Confirmed Balance: {addr_info.get('amount', 0)} BTC")
            print(f"   • Total Received: {addr_info.get('amount', 0)} BTC")
            print(f"   • Transaction Count: {len(txids)}")
            
            # Print transactions
            if txids:
                print("\n📋 Transactions:")
                # Show all transactions if there are 20 or fewer, otherwise show first 10
                display_count = len(txids) if len(txids) <= 20 else 10
                
                for i, txid in enumerate(txids[:display_count]):
                    try:
                        tx_info = btc_service.get_raw_transaction_info(txid)
                        tx_date = "Unknown"
                        if tx_info.get('block_time'):
                            tx_date = datetime.fromtimestamp(tx_info['block_time']).strftime('%Y-%m-%d %H:%M:%S')
                        
                        print(f"   {i+1}. {txid} | Block: {tx_info.get('block_number', 'Unknown')} | Date: {tx_date}")
                    except Exception as e:
                        print(f"   {i+1}. {txid} | Error: {e}")
                
                if len(txids) > display_count:
                    print(f"   ... and {len(txids) - display_count} more transactions")
        else:
            print(f"ℹ️ No transactions found for this address")
        
        # Get UTXOs
        utxos = btc_service._call_rpc("listunspent", [0, 9999999, [address]])
        if utxos and len(utxos) > 0:
            total_balance = sum(utxo.get('amount', 0) for utxo in utxos)
            print(f"\n💰 UTXOs: {len(utxos)} with total balance: {total_balance} BTC")
            
            # Print UTXO details
            for i, utxo in enumerate(utxos[:5]):
                print(f"   {i+1}. {utxo.get('txid', '')}:{utxo.get('vout', '')} | {utxo.get('amount', 0)} BTC")
            
            if len(utxos) > 5:
                print(f"   ... and {len(utxos) - 5} more UTXOs")
        else:
            print("\nℹ️ No UTXOs found for this address")
        
        # Get scan progress
        wallet_info = btc_service._call_rpc("getwalletinfo")
        if 'scanning' in wallet_info:
            scan_progress = wallet_info['scanning']
            if isinstance(scan_progress, dict) and 'progress' in scan_progress:
                print(f"\n⚠️ Wallet rescan is still in progress: {scan_progress['progress']*100:.2f}%")
                if 'duration' in scan_progress:
                    print(f"   Scan has been running for {format_time(scan_progress['duration'])}")
            else:
                print(f"\n✅ No active wallet rescan")
        else:
            print(f"\n✅ No active wallet rescan")
        
        # Update database with balances if requested
        update_db = input("\nUpdate database with this information? (y/n): ").lower() == 'y'
        if update_db:
            db = SessionLocal()
            try:
                monitoring = db.query(BTCAddressMonitoring).filter(
                    BTCAddressMonitoring.bitcoin_address == address
                ).first()
                
                if monitoring:
                    # Update balance
                    balance = Decimal('0')
                    if utxos and len(utxos) > 0:
                        balance = Decimal(str(sum(utxo.get('amount', 0) for utxo in utxos)))
                    
                    monitoring.last_known_balance = balance
                    
                    # Update last activity
                    if txids:
                        most_recent_tx = None
                        most_recent_block = None
                        
                        # Find most recent transaction
                        for txid in txids:
                            try:
                                tx_info = btc_service.get_raw_transaction_info(txid)
                                block_num = tx_info.get('block_number')
                                
                                if block_num and (most_recent_block is None or block_num > most_recent_block):
                                    most_recent_block = block_num
                                    most_recent_tx = txid
                            except Exception:
                                pass
                        
                        if most_recent_tx:
                            monitoring.last_transaction_hash = most_recent_tx
                        
                        if most_recent_block:
                            monitoring.last_activity_block = most_recent_block
                    
                    # Update last check time and block
                    monitoring.last_check_timestamp = datetime.utcnow()
                    chain_info = btc_service._call_rpc("getblockchaininfo")
                    monitoring.last_block_checked = chain_info['blocks']
                    
                    db.commit()
                    print(f"✅ Database updated successfully")
                else:
                    print(f"❌ Address not found in database")
            finally:
                db.close()
        
        return True
        
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_all_addresses():
    """Verify all addresses in the database"""
    db = SessionLocal()
    try:
        addresses = db.query(BTCAddressMonitoring).all()
        if not addresses:
            print("No addresses found in database.")
            return
            
        print(f"Found {len(addresses)} addresses to verify")
        
        for i, addr in enumerate(addresses):
            print(f"\nVerifying address {i+1}/{len(addresses)}: {addr.bitcoin_address}")
            verify_address_import(addr.bitcoin_address)
            
            # Ask to continue after each address
            if i < len(addresses) - 1:
                if input("\nContinue to next address? (y/n): ").lower() != 'y':
                    print("Verification stopped.")
                    break
    finally:
        db.close()

def check_rescan_status():
    """Check if a rescan is currently in progress"""
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("❌ Bitcoin Core RPC not available. Exiting.")
        return
        
    try:
        btc_service.load_watch_wallet()
        wallet_info = btc_service._call_rpc("getwalletinfo")
        
        if 'scanning' in wallet_info:
            scan_progress = wallet_info['scanning']
            if isinstance(scan_progress, dict) and 'progress' in scan_progress:
                print(f"\n⚠️ Wallet rescan is in progress: {scan_progress['progress']*100:.2f}%")
                if 'duration' in scan_progress:
                    print(f"   Scan has been running for {format_time(scan_progress['duration'])}")
            else:
                print(f"\n✅ No active wallet rescan")
        else:
            print(f"\n✅ No active wallet rescan")
    except Exception as e:
        print(f"❌ Error checking rescan status: {e}")

if __name__ == "__main__":
    print("Bitcoin Address Import Verification Tool")
    print("=======================================")
    print("1. Verify a single address")
    print("2. Verify all addresses in database")
    print("3. Check rescan status")
    print("4. Exit")
    
    choice = input("\nSelect an option (1-4): ")
    
    if choice == '1':
        address = input("Enter Bitcoin address to verify: ")
        if address:
            verify_address_import(address)
    elif choice == '2':
        verify_all_addresses()
    elif choice == '3':
        check_rescan_status()
    else:
        print("Exiting.") 