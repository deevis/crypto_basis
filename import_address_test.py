#!/usr/bin/env python3
import time
import logging
from datetime import datetime
from decimal import Decimal
from btc_service import BTCService
from db_config import SessionLocal
from models import BTCAddressMonitoring
import requests
import urllib.parse
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Helper function to format balance
def format_btc(amount):
    if amount is None:
        return "0.00000000"
    return f"{float(amount):.8f}"

def import_and_check_address(address):
    """Import a Bitcoin address as watch-only and check its history"""
    print(f"\n{'='*80}")
    print(f"🔍 Testing watch-only import for: {address}")
    print(f"{'='*80}")
    
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("❌ Bitcoin Core RPC not available. Exiting.")
        return False
    
    # Ensure wallet is loaded
    try:
        btc_service.load_watch_wallet()
        print("✅ Watch wallet loaded")
        
        # Print wallet info for debugging
        wallet_path = btc_service.wallet_path
        print(f"📂 Using wallet: {wallet_path}")
        
        # Fix URL encoding for wallet path
        encoded_wallet_path = urllib.parse.quote(wallet_path)
        print(f"📂 URL-encoded wallet path: {encoded_wallet_path}")
    except Exception as e:
        print(f"❌ Error loading wallet: {e}")
        return False
    
    # Step 1: Import the address
    print(f"\n1. Importing address {address} to watch-only wallet...")
    start_time = time.time()
    
    try:
        # Need to modify _call_rpc to handle importaddress as a wallet-specific command
        # Create a custom version of the call for our test
        url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_path}"
        print(f"   Using wallet URL: {url}")
        
        headers = {'content-type': 'application/json'}
        payload = {
            "jsonrpc": "1.0",
            "id": "crypto-basis",
            "method": "importaddress",
            "params": [address, "test-import", False]
        }
        
        auth = (btc_service.user, btc_service.password)
        response = requests.post(url, json=payload, headers=headers, auth=auth, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Error: RPC call failed with status {response.status_code}")
            print(f"   Response text: {response.text}")
            return False
        
        result = response.json()
        if result.get('error'):
            print(f"❌ Error in RPC call: {result['error']}")
            return False
        
        elapsed = time.time() - start_time
        print(f"✅ Address imported successfully in {elapsed:.2f} seconds")
        
        # Step 2: Verify it's in wallet
        print("\n2. Verifying address is in wallet...")
        # Again, make sure to use the wallet path
        verify_url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_path}"
        payload = {
            "jsonrpc": "1.0",
            "id": "crypto-basis",
            "method": "getaddressinfo", 
            "params": [address]
        }
        
        response = requests.post(verify_url, json=payload, headers=headers, auth=auth, timeout=30)
        if response.status_code != 200:
            print(f"❌ Error: RPC call failed with status {response.status_code}")
            print(f"   Response text: {response.text}")
            return False
            
        result = response.json()
        if result.get('error'):
            print(f"❌ Error in RPC call: {result['error']}")
            return False
            
        addresses = result.get('result', {})
        
        # Print the full response for debugging
        print(f"   Full getaddressinfo response:")
        print(json.dumps(addresses, indent=2))
        
        if addresses and addresses.get('iswatchonly', False):
            print(f"✅ Address confirmed as watch-only")
        else:
            print(f"❌ Address not properly imported as watch-only")
            print(f"   iswatchonly: {addresses.get('iswatchonly')}")
            
            # Try an alternative approach
            print("\n   Trying listreceivedbyaddress as alternative verification...")
            alt_url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_path}"
            payload = {
                "jsonrpc": "1.0",
                "id": "crypto-basis",
                "method": "listreceivedbyaddress", 
                "params": [0, True, True]
            }
            
            response = requests.post(alt_url, json=payload, headers=headers, auth=auth, timeout=30)
            received = response.json().get('result', [])
            
            found = False
            for entry in received:
                if entry.get('address') == address:
                    found = True
                    print(f"   ✅ Address found in listreceivedbyaddress!")
                    break
            
            if not found:
                print(f"   ❌ Address not found in listreceivedbyaddress either")
                return False
        
        # Step 3 onwards - use encoded_wallet_path instead of wallet_path
        # Continue with direct wallet RPC calls for the rest of the steps
        # Step 3: Get transactions for this address
        print("\n3. Checking for transactions (this might take a while)...")
        start_time = time.time()
        
        # Make sure we're using the wallet path for this call too
        tx_url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_path}"
        payload = {
            "jsonrpc": "1.0",
            "id": "crypto-basis",
            "method": "listreceivedbyaddress",
            "params": [0, True, True, address]
        }
        
        response = requests.post(tx_url, json=payload, headers=headers, auth=auth, timeout=30)
        result = response.json().get('result', [])
        elapsed = time.time() - start_time
        
        if result and len(result) > 0:
            print(f"✅ Found transaction history in {elapsed:.2f} seconds")
            
            # Print transaction details
            addr_info = result[0]
            print(f"\n📝 Address Summary:")
            print(f"   • Confirmed Balance: {addr_info.get('amount', 0)} BTC")
            print(f"   • Total Received: {addr_info.get('amount', 0)} BTC")
            print(f"   • Transaction Count: {len(addr_info.get('txids', []))}")
            
            # Print first 5 transactions
            print("\n📋 Recent Transactions:")
            txids = addr_info.get('txids', [])
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
            print(f"ℹ️ No transactions found for this address in {elapsed:.2f} seconds")
        
        # Step 4: Get the UTXO set for this address
        print("\n4. Checking UTXOs for this address...")
        utxo_url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_path}"
        payload = {
            "jsonrpc": "1.0",
            "id": "crypto-basis",
            "method": "listunspent",
            "params": [0, 9999999, [address]]
        }
        
        response = requests.post(utxo_url, json=payload, headers=headers, auth=auth, timeout=30)
        utxos = response.json().get('result', [])
        
        if utxos and len(utxos) > 0:
            total_balance = sum(utxo.get('amount', 0) for utxo in utxos)
            print(f"✅ Found {len(utxos)} UTXOs with total balance: {total_balance} BTC")
            
            # Print UTXO details
            for i, utxo in enumerate(utxos[:5]):
                print(f"   {i+1}. {utxo.get('txid', '')}:{utxo.get('vout', '')} | {utxo.get('amount', 0)} BTC")
            
            if len(utxos) > 5:
                print(f"   ... and {len(utxos) - 5} more UTXOs")
        else:
            print("ℹ️ No UTXOs found for this address")
        
        # Step 5: Compare with scantxoutset (which doesn't require import)
        print("\n5. Comparing with scantxoutset (direct UTXO scan)...")
        start_time = time.time()
        scan_result = btc_service._call_rpc("scantxoutset", ["start", [f"addr({address})"]])
        elapsed = time.time() - start_time
        
        if scan_result and scan_result.get('success'):
            total_amount = scan_result.get('total_amount', 0)
            unspents = scan_result.get('unspents', [])
            print(f"✅ scantxoutset found {len(unspents)} UTXOs with total balance: {total_amount} BTC in {elapsed:.2f} seconds")
            
            # Print first few unspents
            for i, utxo in enumerate(unspents[:5]):
                print(f"   {i+1}. {utxo.get('txid', '')}:{utxo.get('vout', '')} | {utxo.get('amount', 0)} BTC")
            
            if len(unspents) > 5:
                print(f"   ... and {len(unspents) - 5} more UTXOs")
        else:
            print(f"ℹ️ scantxoutset found no UTXOs in {elapsed:.2f} seconds")
        
        print("\n✅ Watch-only import test completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error during import test: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_monitored_address():
    """Get a single address from the monitoring table to test"""
    db = SessionLocal()
    try:
        address = db.query(BTCAddressMonitoring).first()
        if address:
            return address.bitcoin_address
        else:
            print("No addresses found in the BTCAddressMonitoring table")
            return None
    finally:
        db.close()

if __name__ == "__main__":
    # Get an address to test
    test_address = get_monitored_address()
    
    if test_address:
        print(f"Testing with address: {test_address}")
        import_and_check_address(test_address)
    else:
        print("Please provide a bitcoin address to test")
        address = input("Enter Bitcoin address: ")
        if address:
            import_and_check_address(address) 