#!/usr/bin/env python3
import time
import logging
import json
import urllib.parse
import requests
import sys
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

def import_address_with_rescan(address, origin_block=None, use_importmulti=True, async_mode=True):
    """
    Import a Bitcoin address with proper rescan
    
    Args:
        address: The Bitcoin address to import
        origin_block: Optional block number to start rescan from
        use_importmulti: Whether to use importmulti (more efficient) or importaddress
        async_mode: If True, doesn't wait for rescan to complete (recommended for large rescans)
    """
    print(f"\n{'='*80}")
    print(f"🔄 Importing address with rescan: {address}")
    if origin_block:
        print(f"   Starting from block: {origin_block}")
    print(f"{'='*80}")
    
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("❌ Bitcoin Core RPC not available. Exiting.")
        return False
    
    # Ensure wallet is loaded - handle "already loaded" error gracefully
    try:
        # Try to load wallet but don't fail if it's already loaded
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
        encoded_wallet_path = urllib.parse.quote(wallet_path)
        print(f"📂 Using wallet: {wallet_path} (encoded: {encoded_wallet_path})")
        
        # Get current blockchain info
        chain_info = btc_service._call_rpc("getblockchaininfo")
        current_height = chain_info['blocks']
        print(f"📊 Current blockchain height: {current_height}")
        
        # If origin block is provided, get timestamp
        start_timestamp = None
        if origin_block:
            try:
                block_hash = btc_service._call_rpc("getblockhash", [origin_block])
                block_info = btc_service._call_rpc("getblockheader", [block_hash])
                start_timestamp = block_info.get('time', None)
                if start_timestamp:
                    start_date = datetime.fromtimestamp(start_timestamp)
                    print(f"📅 Origin block timestamp: {start_date} ({start_timestamp})")
            except Exception as e:
                print(f"⚠️ Warning: Couldn't get timestamp for block {origin_block}: {e}")
                start_timestamp = None
        
        # Estimate rescan time
        blocks_to_rescan = current_height - (origin_block or 0)
        rescan_estimate = blocks_to_rescan * 0.1  # More realistic estimate: 10 blocks per second
        print(f"⏱️ Estimated rescan time: {format_time(rescan_estimate)} for {blocks_to_rescan} blocks")
        
        # Confirm action
        if input("❓ Start import with rescan? This might take a long time. (y/n): ").lower() != 'y':
            print("❌ Import cancelled.")
            return False
            
        # Set a longer timeout for rescan operations (if not in async mode)
        timeout = 3600 if not async_mode else 10  # 1 hour or 10 seconds for async
        
        print(f"\n⏳ Starting import at {datetime.now().strftime('%H:%M:%S')}")
        if async_mode:
            print(f"🔄 Running in ASYNC mode - will timeout after {timeout} seconds (this is expected)")
            print(f"   The rescan will continue on the Bitcoin Core node even after this script exits.")
            print(f"   You can check the progress by looking at the Bitcoin Core UI or debug.log")
        
        # Start the import
        start_time = time.time()
        import_success = False
        
        try:
            if use_importmulti and start_timestamp:
                # Use importmulti with timestamp for more efficient rescan
                print(f"🔍 Using importmulti with timestamp {start_timestamp}")
                
                request = [{
                    "scriptPubKey": { "address": address },
                    "timestamp": start_timestamp,
                    "watchonly": True,
                    "label": f"monitored-{address[:8]}",
                    "rescan": True
                }]
                
                result = btc_service._call_rpc("importmulti", [request, {"rescan": True}], timeout=timeout)
                if result[0].get('success'):
                    print(f"✅ Successfully imported address with timestamp rescan")
                    import_success = True
                else:
                    print(f"❌ Import failed: {result[0].get('error', {}).get('message', 'Unknown error')}")
                    return False
            else:
                # Use standard importaddress with full rescan
                print(f"🔍 Using importaddress with full rescan")
                # Use a direct HTTP call with longer timeout
                import_url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_path}"
                headers = {'content-type': 'application/json'}
                payload = {
                    "jsonrpc": "1.0",
                    "id": "crypto-basis",
                    "method": "importaddress",
                    "params": [address, f"monitored-{address[:8]}", True]
                }
                
                auth = (btc_service.user, btc_service.password)
                
                try:
                    response = requests.post(import_url, json=payload, headers=headers, auth=auth, timeout=timeout)
                    
                    if response.status_code == 200:
                        result = response.json()
                        if result.get('error'):
                            print(f"❌ Import failed: {result['error']}")
                            return False
                        import_success = True
                        print(f"✅ Successfully completed importaddress with rescan")
                    else:
                        print(f"❌ HTTP error: {response.status_code}")
                        print(f"   Response: {response.text}")
                        # Treat as timeout/expected error if async mode
                        import_success = async_mode
                except requests.exceptions.Timeout:
                    # In async mode, timeout is expected and fine
                    if async_mode:
                        print(f"ℹ️ Request timed out as expected in async mode")
                        print(f"✅ Import command was sent successfully, rescan is happening on the node")
                        import_success = True
                    else:
                        print(f"❌ Request timed out - try using async mode for large rescans")
                        return False
        except Exception as e:
            # In async mode, many errors are expected and fine
            if async_mode and "timeout" in str(e).lower():
                print(f"ℹ️ Connection timed out as expected in async mode")
                print(f"✅ Import command was sent successfully, rescan is happening on the node")
                import_success = True
            else:
                print(f"❌ Error during import: {e}")
                return False
        
        # Check how long it took (if completed)
        elapsed = time.time() - start_time
        
        if import_success:
            if async_mode:
                print(f"\n✅ Import command sent successfully and is running on the node")
                print(f"⏱️ Script ran for {format_time(elapsed)}")
                print(f"\n⚠️ IMPORTANT: The rescan is still in progress on your Bitcoin Core node.")
                print(f"   You can monitor progress in the Bitcoin Core UI or debug.log")
                print(f"   Do NOT shut down Bitcoin Core until the rescan is complete!")
                print(f"   Run the verify_import.py script later to check results when the rescan is done.")
                return True
            else:
                print(f"⏱️ Import and rescan completed in {format_time(elapsed)}")
        
        # Skip verification in async mode (rescan is still running)
        if async_mode:
            return import_success
            
        # Verify the import
        print("\n🔍 Verifying import success...")
        
        # Check address info
        address_info = btc_service._call_rpc("getaddressinfo", [address])
        if not address_info.get('iswatchonly', False):
            print(f"⚠️ Warning: Address is not showing as watch-only. This is unexpected.")
        
        # Get transactions
        received = btc_service._call_rpc("listreceivedbyaddress", [0, True, True, address])
        if received and len(received) > 0:
            addr_info = received[0]
            txids = addr_info.get('txids', [])
            
            print(f"\n📝 Address Summary After Import:")
            print(f"   • Confirmed Balance: {addr_info.get('amount', 0)} BTC")
            print(f"   • Total Received: {addr_info.get('amount', 0)} BTC")
            print(f"   • Transaction Count: {len(txids)}")
            
            # Print first 5 transactions
            if txids:
                print("\n📋 Recent Transactions:")
                for i, txid in enumerate(txids[:5]):
                    try:
                        tx_info = btc_service.get_raw_transaction_info(txid)
                        tx_date = "Unknown"
                        if tx_info.get('block_time'):
                            tx_date = datetime.fromtimestamp(tx_info['block_time']).strftime('%Y-%m-%d %H:%M:%S')
                        
                        print(f"   {i+1}. {txid} | Block: {tx_info.get('block_number', 'Unknown')} | Date: {tx_date}")
                    except Exception as e:
                        print(f"   {i+1}. {txid} | Error: {e}")
                
                if len(txids) > 5:
                    print(f"   ... and {len(txids) - 5} more transactions")
        else:
            print(f"ℹ️ No transactions found for this address")
        
        # Get UTXOs
        utxos = btc_service._call_rpc("listunspent", [0, 9999999, [address]])
        if utxos and len(utxos) > 0:
            total_balance = sum(utxo.get('amount', 0) for utxo in utxos)
            print(f"\n💰 UTXOs: {len(utxos)} with total balance: {total_balance} BTC")
        else:
            print("\nℹ️ No UTXOs found for this address")
        
        print(f"\n✅ Address import completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error during address import: {e}")
        import traceback
        traceback.print_exc()
        return False

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

def get_monitored_addresses():
    """Get all addresses from the monitoring table that need proper import"""
    db = SessionLocal()
    try:
        addresses = db.query(BTCAddressMonitoring).all()
        return [(addr.bitcoin_address, addr.origin_block_number) for addr in addresses]
    finally:
        db.close()

def import_single_address():
    """Import a single address specified by the user"""
    address = input("Enter Bitcoin address to import: ")
    if not address:
        print("No address provided. Exiting.")
        return
    
    origin_block = input("Enter origin block number (or leave empty for full rescan): ")
    if origin_block:
        try:
            origin_block = int(origin_block)
        except ValueError:
            print("Invalid block number. Using full rescan.")
            origin_block = None
    else:
        origin_block = None
    
    use_importmulti = input("Use importmulti with timestamp? (more efficient) (y/n): ").lower() == 'y'
    async_mode = input("Run in async mode (recommended for large rescans)? (y/n): ").lower() == 'y'
    
    import_address_with_rescan(address, origin_block, use_importmulti, async_mode)

def import_all_addresses():
    """Import all addresses from the monitoring table"""
    addresses = get_monitored_addresses()
    if not addresses:
        print("No addresses found to import.")
        return
    
    print(f"Found {len(addresses)} addresses to import")
    
    # Use async mode by default for bulk imports
    async_mode = input("Run in async mode (recommended for bulk imports)? (y/n): ").lower() != 'n'
    
    for i, (address, origin_block) in enumerate(addresses):
        print(f"\nProcessing address {i+1}/{len(addresses)}: {address}")
        success = import_address_with_rescan(address, origin_block, use_importmulti=True, async_mode=async_mode)
        
        if not success:
            print(f"⚠️ Failed to import address {address}. Continue with next? (y/n): ")
            if input().lower() != 'y':
                print("Aborting remaining imports.")
                break

def import_all_addresses_batch():
    """Import all addresses from the monitoring table in a single batch call"""
    addresses = get_monitored_addresses()
    if not addresses:
        print("No addresses found to import.")
        return
    
    print(f"\n{'='*80}")
    print(f"🔄 Batch importing {len(addresses)} addresses")
    print(f"{'='*80}")
    
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("❌ Bitcoin Core RPC not available. Exiting.")
        return
    
    # Use the wallet name from BTCService (which now uses BTC_WALLET_NAME env var)
    # No need to override the wallet path since BTCService already has the right one
    print(f"📂 Using wallet: {btc_service.wallet_path}")
    
    # Ensure wallet is loaded
    try:
        btc_service.load_watch_wallet()
        print("✅ Wallet loaded")
    except Exception as e:
        error_text = str(e)
        if "is already loaded" in error_text:
            print("✅ Wallet is already loaded - continuing")
        else:
            print(f"❌ Error loading wallet: {e}")
            return
    
    # Get current blockchain info
    chain_info = btc_service._call_rpc("getblockchaininfo")
    current_height = chain_info['blocks']
    print(f"📊 Current blockchain height: {current_height}")
    
    # Prepare importmulti requests
    import_requests = []
    
    print("\n🔍 Preparing import requests with timestamps...")
    for i, (address, origin_block) in enumerate(addresses):
        print(f"  Processing {i+1}/{len(addresses)}: {address}")
        
        # If origin block is provided, get timestamp
        start_timestamp = None
        if origin_block:
            try:
                block_hash = btc_service._call_rpc("getblockhash", [origin_block])
                block_info = btc_service._call_rpc("getblockheader", [block_hash])
                start_timestamp = block_info.get('time', None)
                if start_timestamp:
                    start_date = datetime.fromtimestamp(start_timestamp)
                    print(f"    📅 Block {origin_block} timestamp: {start_date.strftime('%Y-%m-%d')}")
            except Exception as e:
                print(f"    ⚠️ Warning: Couldn't get timestamp for block {origin_block}: {e}")
                start_timestamp = None
        
        # Use genesis block timestamp if no timestamp available
        if not start_timestamp:
            print(f"    ⚠️ No origin block or timestamp - will use earliest timestamp")
            # Start of 2009 - close to Bitcoin genesis
            start_timestamp = 1231006505
        
        # Add to batch with timestamp - use scriptPubKey format
        import_requests.append({
            "scriptPubKey": {"address": address},  # Use scriptPubKey format
            "timestamp": start_timestamp,
            "watchonly": True,
            "label": f"batch-{address[:8]}",
            "rescan": True
        })
    
    # Execute importmulti with all addresses at once
    if import_requests:
        print(f"\n🔄 Ready to import {len(import_requests)} addresses with timestamps in one batch")
        print(f"⚠️ WARNING: This will start a large rescan operation on your Bitcoin Core node")
        print(f"   Your Bitcoin Core client may be unresponsive during this time")
        print(f"   The script will timeout after sending the request (expected behavior)")
        print(f"   The rescan will continue in the background on your node")
        
        if input("\n❓ Start batch import with rescan? (y/n): ").lower() != 'y':
            print("❌ Batch import cancelled.")
            return
        
        start_time = time.time()
        print(f"\n⏳ Starting batch import at {datetime.now().strftime('%H:%M:%S')}")
        
        try:
            # Make a direct RPC call with wallet path included
            encoded_wallet_path = urllib.parse.quote(btc_service.wallet_path)
            import_url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_path}"
            print(f"📂 Using wallet URL: {import_url}")
            
            headers = {'content-type': 'application/json'}
            payload = {
                "jsonrpc": "1.0",
                "id": "crypto-basis",
                "method": "importmulti",
                "params": [import_requests, {"rescan": True}]
            }
            
            auth = (btc_service.user, btc_service.password)
            
            try:
                # Use a short timeout as we expect this to timeout (async behavior)
                response = requests.post(import_url, json=payload, headers=headers, auth=auth, timeout=30)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('error'):
                        print(f"❌ Import failed: {result['error']}")
                        return False
                    
                    # Process results
                    if 'result' in result and result['result']:
                        result_list = result['result']
                        success_count = sum(1 for r in result_list if r.get('success'))
                        print(f"✅ Successfully imported {success_count} of {len(import_requests)} addresses")
                        
                        # Show errors if any
                        for i, r in enumerate(result_list):
                            if not r.get('success'):
                                addr = addresses[i][0]
                                error = r.get('error', {}).get('message', 'Unknown error')
                                print(f"❌ Failed to import {addr}: {error}")
                else:
                    print(f"❌ HTTP error: {response.status_code}")
                    print(f"   Response: {response.text}")
                    return False
            except requests.exceptions.Timeout:
                # Timeout is expected and fine - operation continues on node
                print(f"ℹ️ Request timed out as expected")
                print(f"✅ Import command was sent successfully, rescan is happening on the node")
                
        except Exception as e:
            if "timeout" in str(e).lower():
                print(f"ℹ️ Connection timed out as expected")
                print(f"✅ Import command was sent successfully, rescan is happening on the node")
            else:
                print(f"❌ Error during batch import: {e}")
                import traceback
                traceback.print_exc()
                return False
        
        elapsed = time.time() - start_time
        print(f"\n✅ Batch import request sent successfully in {format_time(elapsed)}")
        print(f"\n⚠️ IMPORTANT: The rescan is still in progress on your Bitcoin Core node.")
        print(f"   You can monitor progress in the Bitcoin Core UI or debug.log")
        print(f"   Do NOT shut down Bitcoin Core until the rescan is complete!")
        print(f"   Run the verify_import.py script later to check results when the rescan is done.")

if __name__ == "__main__":
    print("Bitcoin Address Import Tool")
    print("==========================")
    print("1. Import a single address")
    print("2. Import all addresses one by one")
    print("3. Import all addresses in one batch (recommended)")
    print("4. Exit")
    
    choice = input("\nSelect an option (1-4): ")
    
    if choice == '1':
        import_single_address()
    elif choice == '2':
        import_all_addresses()
    elif choice == '3':
        import_all_addresses_batch()
    else:
        print("Exiting.") 