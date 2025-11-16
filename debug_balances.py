#!/usr/bin/env python3
"""
Debug script to check Bitcoin address balances and identify issues
"""
import logging
from datetime import datetime
from db_config import SessionLocal
from models import BTCAddressMonitoring
from btc_service import BTCService

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def check_all_balances():
    """Check all monitored addresses and their balances"""
    print("="*80)
    print("BITCOIN ADDRESS BALANCE DEBUG")
    print("="*80)
    
    db = SessionLocal()
    try:
        addresses = db.query(BTCAddressMonitoring).all()
        
        if not addresses:
            print("No addresses found in monitoring table")
            return
        
        print(f"Found {len(addresses)} addresses to check:")
        print()
        
        # Check Bitcoin Core connection
        btc_service = BTCService(test_connection=True)
        btc_available = btc_service.is_available
        
        if btc_available:
            try:
                btc_service.load_watch_wallet()
                print("✅ Bitcoin Core connected and wallet loaded")
            except Exception as e:
                if "is already loaded" in str(e):
                    print("✅ Bitcoin Core connected (wallet already loaded)")
                else:
                    print(f"⚠️ Bitcoin Core connected but wallet issue: {e}")
                    btc_available = False
        else:
            print("❌ Bitcoin Core not available")
        
        print()
        
        for i, addr in enumerate(addresses):
            print(f"{i+1}. Address: {addr.bitcoin_address}")
            print(f"   Source: {addr.source_label}")
            print(f"   Status: {addr.monitor_status}")
            print(f"   Database Balance: {addr.last_known_balance or 'NULL'}")
            print(f"   Last Check: {addr.last_check_timestamp or 'Never'}")
            print(f"   Last Block: {addr.last_block_checked or 'None'}")
            print(f"   Created: {addr.created_at}")
            
            # Check actual balance if Bitcoin Core is available
            if btc_available:
                try:
                    # Get UTXOs
                    utxos = btc_service._call_rpc("listunspent", [0, 9999999, [addr.bitcoin_address]])
                    if utxos:
                        actual_balance = sum(utxo.get('amount', 0) for utxo in utxos)
                        print(f"   Bitcoin Core Balance: {actual_balance:.8f} BTC")
                        
                        if addr.last_known_balance is None:
                            print(f"   ⚠️ Database balance is NULL but Bitcoin Core shows {actual_balance:.8f}")
                        elif abs(float(addr.last_known_balance) - actual_balance) > 0.00000001:
                            print(f"   ⚠️ Balance mismatch! DB: {addr.last_known_balance}, Core: {actual_balance}")
                        else:
                            print(f"   ✅ Balances match")
                    else:
                        print(f"   Bitcoin Core Balance: 0.00000000 BTC")
                        if addr.last_known_balance and float(addr.last_known_balance) > 0:
                            print(f"   ⚠️ Database shows balance but Bitcoin Core shows zero")
                except Exception as e:
                    print(f"   ❌ Error checking Bitcoin Core balance: {e}")
            
            print()
        
        # Check for any recent database modifications
        print("Recent address updates (last 24 hours):")
        from datetime import timedelta
        recent_cutoff = datetime.utcnow() - timedelta(hours=24)
        
        recent_updates = db.query(BTCAddressMonitoring).filter(
            BTCAddressMonitoring.last_check_timestamp >= recent_cutoff
        ).all()
        
        if recent_updates:
            for addr in recent_updates:
                print(f"  - {addr.bitcoin_address}: last check {addr.last_check_timestamp}")
        else:
            print("  No recent updates found")
        
    finally:
        db.close()

def restore_balances_from_bitcoin_core():
    """Restore balances from Bitcoin Core if they were cleared"""
    print("\n" + "="*80)
    print("RESTORING BALANCES FROM BITCOIN CORE")
    print("="*80)
    
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("❌ Bitcoin Core not available - cannot restore balances")
        return False
    
    try:
        btc_service.load_watch_wallet()
    except Exception as e:
        if "is already loaded" not in str(e):
            print(f"❌ Cannot load wallet: {e}")
            return False
    
    db = SessionLocal()
    try:
        # Get addresses with NULL or zero balances that might have actual balances
        addresses = db.query(BTCAddressMonitoring).filter(
            BTCAddressMonitoring.monitor_status == 'active'
        ).all()
        
        updated_count = 0
        
        for addr in addresses:
            try:
                # Get UTXOs from Bitcoin Core
                utxos = btc_service._call_rpc("listunspent", [0, 9999999, [addr.bitcoin_address]])
                
                if utxos:
                    actual_balance = sum(utxo.get('amount', 0) for utxo in utxos)
                    
                    # Update if balance is different
                    if addr.last_known_balance is None or abs(float(addr.last_known_balance or 0) - actual_balance) > 0.00000001:
                        old_balance = addr.last_known_balance
                        addr.last_known_balance = actual_balance
                        addr.last_check_timestamp = datetime.utcnow()
                        
                        print(f"Updated {addr.bitcoin_address}: {old_balance or 'NULL'} -> {actual_balance:.8f}")
                        updated_count += 1
                else:
                    # No UTXOs - set balance to zero if it's not already
                    if addr.last_known_balance is None or float(addr.last_known_balance) != 0:
                        old_balance = addr.last_known_balance
                        addr.last_known_balance = 0
                        addr.last_check_timestamp = datetime.utcnow()
                        
                        print(f"Updated {addr.bitcoin_address}: {old_balance or 'NULL'} -> 0.00000000")
                        updated_count += 1
                        
            except Exception as e:
                print(f"❌ Error updating {addr.bitcoin_address}: {e}")
        
        if updated_count > 0:
            db.commit()
            print(f"\n✅ Updated {updated_count} addresses")
            return True
        else:
            print("\nℹ️ No balances needed updating")
            return True
            
    except Exception as e:
        db.rollback()
        print(f"❌ Error during balance restoration: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("Bitcoin Address Balance Debug Tool")
    print("1. Check all balances")
    print("2. Restore balances from Bitcoin Core")
    print("3. Both")
    
    choice = input("\nSelect option (1-3): ")
    
    if choice in ['1', '3']:
        check_all_balances()
    
    if choice in ['2', '3']:
        if choice == '3':
            restore = input("\nRestore balances from Bitcoin Core? (y/n): ").lower() == 'y'
        else:
            restore = True
            
        if restore:
            restore_balances_from_bitcoin_core() 