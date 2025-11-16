#!/usr/bin/env python3
import os
import sys
import json
import time
import logging
import urllib.parse
import requests
from datetime import datetime
from pathlib import Path

# Add parent directory to path to import btc_service
sys.path.append(str(Path(__file__).parent.parent))
from btc_service import BTCService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def load_monitor_set(json_file_path):
    """Load addresses from a monitor set JSON file"""
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Extract addresses and origin blocks
        addresses = []
        for item in data:
            if isinstance(item, dict) and 'address' in item:
                addresses.append({
                    'address': item['address'],
                    'origin_block': item.get('origin_block'),
                    'owner': item.get('owner', 'Unknown'),
                    'details': item.get('details', '')
                })
        
        return addresses
    except Exception as e:
        logger.error(f"Error loading {json_file_path}: {e}")
        return []

def get_wallet_name_from_file(json_file_path):
    """Generate wallet name from JSON file path"""
    filename = Path(json_file_path).stem  # Get filename without extension
    return f"crypto-basis-{filename}"

def get_wallet_addresses(btc_service, wallet_name):
    """Get all addresses currently in the wallet"""
    try:
        # Temporarily override wallet path for this check
        original_wallet_path = btc_service.wallet_path
        btc_service.wallet_path = wallet_name
        
        # Get all addresses
        received = btc_service._call_rpc("listreceivedbyaddress", [0, True, True])
        addresses = set()
        for addr_info in received:
            if addr_info.get('address'):
                addresses.add(addr_info['address'])
        
        # Restore original wallet path
        btc_service.wallet_path = original_wallet_path
        return addresses
    except Exception as e:
        logger.debug(f"Error getting wallet addresses: {e}")
        return set()

def create_or_load_wallet(btc_service, wallet_name):
    """Create or load a watch-only wallet"""
    try:
        # Try to load existing wallet
        logger.debug(f"Attempting to load wallet: {wallet_name}")
        btc_service._call_rpc("loadwallet", [wallet_name])
        logger.info(f"✅ Loaded existing wallet: {wallet_name}")
        return True
    except Exception as e:
        error_text = str(e)
        logger.debug(f"Load wallet error: {error_text}")
        
        # Check if wallet is already loaded
        if "is already loaded" in error_text:
            logger.info(f"✅ Wallet {wallet_name} is already loaded")
            return True
        
        # Check for various "wallet doesn't exist" error messages
        if any(msg in error_text for msg in [
            "not found",
            "Path does not exist", 
            "Failed to load database path"
        ]):
            logger.info(f"📁 Creating new wallet: {wallet_name}")
            try:
                btc_service._call_rpc("createwallet", [
                    wallet_name,    # wallet name
                    True,          # disable private keys (watch-only)
                    False,         # blank wallet
                    "",            # passphrase
                    False,         # avoid reuse
                    False,         # descriptors - set to False for legacy wallet
                    True           # load on startup
                ])
                logger.info(f"✅ Created new watch-only wallet: {wallet_name}")
                return True
            except Exception as create_error:
                logger.error(f"❌ Failed to create wallet: {create_error}")
                return False
        else:
            logger.error(f"❌ Failed to load wallet with unexpected error: {e}")
            return False

def import_addresses_to_wallet(btc_service, wallet_name, addresses_to_import):
    """Import addresses to a specific wallet using importmulti"""
    if not addresses_to_import:
        logger.info(f"ℹ️ No new addresses to import for wallet {wallet_name}")
        return True
    
    # Temporarily override wallet path
    original_wallet_path = btc_service.wallet_path
    btc_service.wallet_path = wallet_name
    
    try:
        logger.info(f"📥 Importing {len(addresses_to_import)} addresses to wallet {wallet_name}")
        
        # Prepare importmulti requests
        import_requests = []
        for addr_info in addresses_to_import:
            address = addr_info['address']
            origin_block = addr_info.get('origin_block')
            
            # Get timestamp from origin block if available
            start_timestamp = None
            if origin_block:
                try:
                    block_hash = btc_service._call_rpc("getblockhash", [origin_block])
                    block_info = btc_service._call_rpc("getblockheader", [block_hash])
                    start_timestamp = block_info.get('time')
                    if start_timestamp:
                        start_date = datetime.fromtimestamp(start_timestamp)
                        logger.debug(f"  📅 {address} origin block {origin_block}: {start_date.strftime('%Y-%m-%d')}")
                except Exception as e:
                    logger.warning(f"  ⚠️ Couldn't get timestamp for block {origin_block}: {e}")
            
            # Use genesis block timestamp if no origin block
            if not start_timestamp:
                start_timestamp = 1231006505  # Close to Bitcoin genesis
            
            import_requests.append({
                "scriptPubKey": {"address": address},
                "timestamp": start_timestamp,
                "watchonly": True,
                "label": f"{wallet_name}-{address[:8]}",
                "rescan": True
            })
        
        # Execute importmulti
        logger.info(f"🔄 Executing importmulti for {len(import_requests)} addresses...")
        
        # Use direct HTTP call for better timeout control
        encoded_wallet_name = urllib.parse.quote(wallet_name)
        import_url = f"http://{btc_service.host}:{btc_service.port}/wallet/{encoded_wallet_name}"
        
        headers = {'content-type': 'application/json'}
        payload = {
            "jsonrpc": "1.0",
            "id": "crypto-basis-sync",
            "method": "importmulti", 
            "params": [import_requests, {"rescan": True}]
        }
        
        auth = (btc_service.user, btc_service.password)
        
        try:
            # Use short timeout as we expect this might timeout for large imports
            response = requests.post(import_url, json=payload, headers=headers, auth=auth, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('error'):
                    logger.error(f"❌ Import failed: {result['error']}")
                    return False
                
                # Process results
                if 'result' in result and result['result']:
                    result_list = result['result']
                    success_count = sum(1 for r in result_list if r.get('success'))
                    logger.info(f"✅ Successfully imported {success_count} of {len(import_requests)} addresses")
                    
                    # Show errors if any
                    for i, r in enumerate(result_list):
                        if not r.get('success'):
                            addr = addresses_to_import[i]['address']
                            error = r.get('error', {}).get('message', 'Unknown error')
                            logger.warning(f"⚠️ Failed to import {addr}: {error}")
                    
                    return success_count > 0
            else:
                logger.error(f"❌ HTTP error: {response.status_code}")
                return False
                
        except requests.exceptions.Timeout:
            # Timeout is expected for large imports - operation continues on node
            logger.info(f"ℹ️ Import request timed out (expected for large rescans)")
            logger.info(f"✅ Import command sent successfully, rescan happening on node")
            return True
            
    except Exception as e:
        if "timeout" in str(e).lower():
            logger.info(f"ℹ️ Import timed out (expected behavior)")
            return True
        else:
            logger.error(f"❌ Error importing addresses: {e}")
            return False
    finally:
        # Restore original wallet path
        btc_service.wallet_path = original_wallet_path

def sync_monitor_set(json_file_path, btc_service):
    """Sync a single monitor set file"""
    logger.info(f"\n📂 Processing: {json_file_path}")
    
    # Load addresses from JSON file
    addresses = load_monitor_set(json_file_path)
    if not addresses:
        logger.warning(f"⚠️ No addresses found in {json_file_path}")
        return False
    
    logger.info(f"📋 Found {len(addresses)} addresses in monitor set")
    
    # Get wallet name
    wallet_name = get_wallet_name_from_file(json_file_path)
    logger.info(f"🏦 Target wallet: {wallet_name}")
    
    # Create or load wallet
    if not create_or_load_wallet(btc_service, wallet_name):
        logger.error(f"❌ Failed to create/load wallet {wallet_name}")
        return False
    
    # Get currently imported addresses
    existing_addresses = get_wallet_addresses(btc_service, wallet_name)
    logger.info(f"📊 Wallet currently has {len(existing_addresses)} addresses")
    
    # Find addresses that need to be imported
    target_addresses = {addr['address'] for addr in addresses}
    missing_addresses = target_addresses - existing_addresses
    
    if missing_addresses:
        logger.info(f"➕ Need to import {len(missing_addresses)} new addresses")
        addresses_to_import = [addr for addr in addresses if addr['address'] in missing_addresses]
        
        if not import_addresses_to_wallet(btc_service, wallet_name, addresses_to_import):
            logger.error(f"❌ Failed to import addresses to {wallet_name}")
            return False
    else:
        logger.info(f"✅ All addresses already present in wallet")
    
    logger.info(f"✅ Successfully synced monitor set: {Path(json_file_path).stem}")
    return True

def main():
    """Main sync function"""
    print("🔄 Monitor Sets Sync Tool")
    print("=" * 50)
    
    # Initialize Bitcoin service
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("❌ Bitcoin Core RPC not available. Exiting.")
        return
    
    # Get monitor_sets directory
    monitor_sets_dir = Path(__file__).parent
    logger.info(f"📁 Scanning directory: {monitor_sets_dir}")
    
    # Find all JSON files
    json_files = list(monitor_sets_dir.glob("*.json"))
    if not json_files:
        logger.warning("⚠️ No JSON files found in monitor_sets directory")
        return
    
    logger.info(f"📋 Found {len(json_files)} JSON files to process")
    
    # Process each JSON file
    success_count = 0
    for json_file in json_files:
        try:
            if sync_monitor_set(json_file, btc_service):
                success_count += 1
        except Exception as e:
            logger.error(f"❌ Error processing {json_file}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n📊 Sync Summary:")
    print(f"   ✅ Successfully synced: {success_count}")
    print(f"   ❌ Failed: {len(json_files) - success_count}")
    print(f"   📁 Total files: {len(json_files)}")
    
    if success_count < len(json_files):
        print(f"\n⚠️ Some sync operations may still be running on the Bitcoin Core node.")
        print(f"   Monitor your Bitcoin Core logs for rescan progress.")

if __name__ == "__main__":
    main() 