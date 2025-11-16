#!/usr/bin/env python3
import os
import sys
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from decimal import Decimal
import urllib.parse

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

def ensure_log_directory():
    """Create log directory if it doesn't exist"""
    log_dir = Path(__file__).parent.parent / "log"
    log_dir.mkdir(exist_ok=True)
    return log_dir

def generate_run_summary_filename():
    """Generate filename for run summary"""
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return f"check-activity-{timestamp}.json"

def save_run_summary(summary_data):
    """Save run summary to log file"""
    try:
        log_dir = ensure_log_directory()
        summary_file = log_dir / generate_run_summary_filename()
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, default=str)
        
        logger.info(f"📄 Run summary saved to: {summary_file}")
        return str(summary_file)
    except Exception as e:
        logger.error(f"❌ Error saving run summary: {e}")
        return None

def load_all_monitor_sets():
    """Load all addresses from all monitor set JSON files"""
    monitor_sets_dir = Path(__file__).parent
    json_files = list(monitor_sets_dir.glob("*.json"))
    
    all_addresses = {}  # address -> {set_name, owner, details}
    
    for json_file in json_files:
        set_name = json_file.stem
        logger.info(f"📂 Loading monitor set: {set_name}")
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for item in data:
                if isinstance(item, dict) and 'address' in item:
                    address = item['address']
                    all_addresses[address] = {
                        'set_name': set_name,
                        'owner': item.get('owner', 'Unknown'),
                        'details': item.get('details', ''),
                        'origin_block': item.get('origin_block')
                    }
                    
        except Exception as e:
            logger.error(f"❌ Error loading {json_file}: {e}")
    
    logger.info(f"📋 Loaded {len(all_addresses)} addresses from {len(json_files)} monitor sets")
    return all_addresses

def get_wallet_name_from_set(set_name):
    """Generate wallet name from set name"""
    return f"crypto-basis-{set_name}"

def ensure_activity_directory(set_name):
    """Create activity directory for a monitor set if it doesn't exist"""
    activity_dir = Path(__file__).parent / set_name
    activity_dir.mkdir(exist_ok=True)
    return activity_dir

def load_existing_activity(activity_file_path):
    """Load existing activity data for an address"""
    if not activity_file_path.exists():
        return []
    
    try:
        with open(activity_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"⚠️ Error loading existing activity from {activity_file_path}: {e}")
        return []

def save_activity_data(activity_file_path, activity_data):
    """Save activity data to file"""
    try:
        # Sort by date (newest first)
        activity_data.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        with open(activity_file_path, 'w', encoding='utf-8') as f:
            json.dump(activity_data, f, indent=2, default=str)
        return True
    except Exception as e:
        logger.error(f"❌ Error saving activity to {activity_file_path}: {e}")
        return False

def get_address_transactions(btc_service, wallet_name, address):
    """Get all transactions for an address from its wallet"""
    try:
        # Temporarily override wallet path
        original_wallet_path = btc_service.wallet_path
        btc_service.wallet_path = wallet_name
        
        # Get received transactions
        received = btc_service._call_rpc("listreceivedbyaddress", [0, True, True, address])
        
        # Restore wallet path
        btc_service.wallet_path = original_wallet_path
        
        if received and len(received) > 0:
            return received[0].get('txids', [])
        
        return []
    except Exception as e:
        logger.debug(f"Error getting transactions for {address}: {e}")
        return []

def get_transaction_details(btc_service, txid, address):
    """Get detailed transaction information for a specific address"""
    try:
        # Get raw transaction
        raw_tx = btc_service._call_rpc("getrawtransaction", [txid, True])
        
        # Find the output that pays to our address
        amount = Decimal('0')
        found_output = False
        
        for vout in raw_tx['vout']:
            script_pub_key = vout['scriptPubKey']
            output_addresses = []
            
            # Handle both address formats
            if 'address' in script_pub_key:
                output_addresses.append(script_pub_key['address'])
            elif 'addresses' in script_pub_key:
                output_addresses.extend(script_pub_key['addresses'])
            
            if address in output_addresses:
                amount = Decimal(str(vout['value']))
                found_output = True
                break
        
        if not found_output:
            logger.warning(f"⚠️ Address {address} not found in transaction {txid} outputs")
            return None
        
        # Get block information
        block_hash = raw_tx.get('blockhash')
        block_info = None
        block_number = None
        block_time = None
        
        if block_hash:
            try:
                block_info = btc_service._call_rpc("getblock", [block_hash])
                block_number = block_info.get('height')
                block_time = datetime.fromtimestamp(block_info.get('time', 0))
            except Exception as e:
                logger.warning(f"⚠️ Error getting block info for {block_hash}: {e}")
        
        return {
            'txid': txid,
            'amount': float(amount),
            'block_number': block_number,
            'block_hash': block_hash,
            'date': block_time.isoformat() if block_time else None,
            'confirmations': raw_tx.get('confirmations', 0)
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting transaction details for {txid}: {e}")
        return None

def get_address_utxos(btc_service, wallet_name, address):
    """Get current UTXOs for an address"""
    try:
        # Temporarily override wallet path
        original_wallet_path = btc_service.wallet_path
        btc_service.wallet_path = wallet_name
        
        # Get UTXOs
        utxos = btc_service._call_rpc("listunspent", [0, 9999999, [address]])
        
        # Restore wallet path
        btc_service.wallet_path = original_wallet_path
        
        # Format UTXO data
        utxo_data = []
        total_balance = Decimal('0')
        
        for utxo in utxos:
            amount = Decimal(str(utxo.get('amount', 0)))
            total_balance += amount
            
            utxo_data.append({
                'txid': utxo.get('txid'),
                'vout': utxo.get('vout'),
                'amount': float(amount),
                'confirmations': utxo.get('confirmations', 0),
                'spendable': utxo.get('spendable', False),
                'safe': utxo.get('safe', False)
            })
        
        return utxo_data, float(total_balance)
        
    except Exception as e:
        logger.debug(f"Error getting UTXOs for {address}: {e}")
        return [], 0.0

def check_address_activity(btc_service, address, address_info):
    """Check for new activity on a specific address"""
    set_name = address_info['set_name']
    wallet_name = get_wallet_name_from_set(set_name)
    
    logger.debug(f"🔍 Checking activity for {address} (wallet: {wallet_name})")
    
    # Ensure activity directory exists
    activity_dir = ensure_activity_directory(set_name)
    activity_file = activity_dir / f"{address}.json"
    
    # Load existing activity
    existing_activity = load_existing_activity(activity_file)
    existing_txids = {activity.get('txid') for activity in existing_activity if activity.get('txid')}
    
    # Get current transactions
    try:
        current_txids = get_address_transactions(btc_service, wallet_name, address)
    except Exception as e:
        logger.warning(f"⚠️ Error getting transactions for {address}: {e}")
        return False, []
    
    # Find new transactions
    new_txids = [txid for txid in current_txids if txid not in existing_txids]
    
    if not new_txids:
        logger.debug(f"ℹ️ No new transactions for {address}")
        return True, []
    
    logger.info(f"🆕 Found {len(new_txids)} new transactions for {address}")
    
    # Process new transactions
    new_activities = []
    running_balance = 0.0
    
    # Calculate starting balance from existing activities
    if existing_activity:
        # Sort existing by block number/date
        existing_sorted = sorted(existing_activity, key=lambda x: (
            x.get('block_number', 0),
            x.get('date', '')
        ))
        if existing_sorted:
            running_balance = existing_sorted[-1].get('balance_after', 0.0)
    
    # Process new transactions in chronological order
    new_tx_details = []
    for txid in new_txids:
        tx_details = get_transaction_details(btc_service, txid, address)
        if tx_details:
            new_tx_details.append(tx_details)
    
    # Sort by block number and date
    new_tx_details.sort(key=lambda x: (
        x.get('block_number', 0),
        x.get('date', '')
    ))
    
    # Build activity records
    for tx_details in new_tx_details:
        running_balance += tx_details['amount']
        
        # Get current UTXOs
        utxos, current_balance = get_address_utxos(btc_service, wallet_name, address)
        
        activity_record = {
            'txid': tx_details['txid'],
            'block_number': tx_details['block_number'],
            'date': tx_details['date'],
            'amount': tx_details['amount'],
            'balance_after': running_balance,
            'current_balance': current_balance,  # Real-time balance
            'confirmations': tx_details['confirmations'],
            'utxos': utxos,
            'last_updated': datetime.now().isoformat()
        }
        
        new_activities.append(activity_record)
        logger.info(f"  📝 Transaction {tx_details['txid'][:16]}... | Amount: {tx_details['amount']} BTC | Balance: {current_balance} BTC")
    
    # Combine with existing activity and save
    all_activity = existing_activity + new_activities
    
    if save_activity_data(activity_file, all_activity):
        logger.info(f"💾 Saved {len(new_activities)} new activities for {address}")
        return True, new_activities
    else:
        logger.error(f"❌ Failed to save activity data for {address}")
        return False, new_activities

def check_all_activity(btc_service, addresses):
    """Check activity for all addresses"""
    logger.info(f"🔍 Checking activity for {len(addresses)} addresses...")
    
    success_count = 0
    error_count = 0
    address_activities = {}  # address -> activity data for summary
    
    for i, (address, address_info) in enumerate(addresses.items()):
        try:
            logger.info(f"📍 ({i+1}/{len(addresses)}) Checking {address} ({address_info['owner']})")
            
            success, new_activities = check_address_activity(btc_service, address, address_info)
            
            # Store activity data for summary
            address_activities[address] = {
                'owner': address_info['owner'],
                'set_name': address_info['set_name'],
                'details': address_info.get('details', ''),
                'origin_block': address_info.get('origin_block'),
                'success': success,
                'new_activities': new_activities,
                'activity_count': len(new_activities)
            }
            
            if success:
                success_count += 1
            else:
                error_count += 1
                
        except Exception as e:
            logger.error(f"❌ Error checking activity for {address}: {e}")
            error_count += 1
            
            # Store error info for summary
            address_activities[address] = {
                'owner': address_info.get('owner', 'Unknown'),
                'set_name': address_info.get('set_name', 'Unknown'),
                'details': address_info.get('details', ''),
                'origin_block': address_info.get('origin_block'),
                'success': False,
                'error': str(e),
                'new_activities': [],
                'activity_count': 0
            }
            
            import traceback
            traceback.print_exc()
        
        # Brief pause between addresses to avoid overwhelming the RPC
        time.sleep(0.1)
    
    return success_count, error_count, address_activities

def main():
    """Main activity checking function"""
    print("🔍 Monitor Sets Activity Checker")
    print("=" * 50)
    
    # Initialize Bitcoin service
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("❌ Bitcoin Core RPC not available. Exiting.")
        return
    
    # Load all addresses from monitor sets
    addresses = load_all_monitor_sets()
    if not addresses:
        logger.warning("⚠️ No addresses found to monitor")
        return
    
    # Check activity for all addresses
    start_time = time.time()
    success_count, error_count, address_activities = check_all_activity(btc_service, addresses)
    elapsed_time = time.time() - start_time
    
    print(f"\n📊 Activity Check Summary:")
    print(f"   ✅ Successfully checked: {success_count}")
    print(f"   ❌ Errors: {error_count}")
    print(f"   📁 Total addresses: {len(addresses)}")
    print(f"   ⏱️ Time elapsed: {elapsed_time:.2f} seconds")
    
    # Count addresses with new activity
    addresses_with_activity = sum(1 for addr_data in address_activities.values() 
                                 if addr_data['activity_count'] > 0)
    total_new_activities = sum(addr_data['activity_count'] for addr_data in address_activities.values())
    
    print(f"   🆕 Addresses with new activity: {addresses_with_activity}")
    print(f"   📝 Total new transactions: {total_new_activities}")
    
    if error_count > 0:
        print(f"\n⚠️ Some addresses had errors. Check the logs above for details.")

    # Create comprehensive run summary
    summary_data = {
        "run_info": {
            "timestamp": datetime.now().isoformat(),
            "success_count": success_count,
            "error_count": error_count,
            "total_addresses": len(addresses),
            "addresses_with_activity": addresses_with_activity,
            "total_new_activities": total_new_activities,
            "time_elapsed": elapsed_time
        },
        "addresses": address_activities
    }
    
    summary_file = save_run_summary(summary_data)
    if summary_file:
        print(f"📄 Run summary saved to: {summary_file}")

if __name__ == "__main__":
    main() 