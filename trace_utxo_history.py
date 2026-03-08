#!/usr/bin/env python3
"""
UTXO History Tracer

Traces the history of Bitcoin UTXOs backwards through the blockchain until
reaching a coinbase (mining) transaction or an exchange-like transaction.

Usage:
    python trace_utxo_history.py <bitcoin_address> [options]
    python trace_utxo_history.py --all [options]

Arguments:
    bitcoin_address         Bitcoin address to trace (or use --all for all monitored)
    --all                   Trace ALL monitored addresses
    --clear                 Clear existing trace data before starting
    --max-hops N            Maximum depth per trace branch (default: 10)
    --max-transactions N    Maximum total transactions to explore per UTXO (default: 100)
    --save                  Save trace results to database (includes graph tables)
    --verbose               Show detailed output for each hop
    --use-watch-wallet      Query Bitcoin Core watch wallet instead of using database UTXOs

Examples:
    python trace_utxo_history.py bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh
    python trace_utxo_history.py --all --save --clear
    python trace_utxo_history.py --all --max-hops 5 --max-transactions 50 --save
"""

import argparse
import sys
import json
import logging
from datetime import datetime
from decimal import Decimal

from db_config import SessionLocal
from models import (
    BTCAddressMonitoring, BTCAddressUTXO, BTCUTXOTraceHistory, TraceTerminationReason,
    BTCTracedTransaction, BTCTracedAddress, BTCTransactionFlow, TransactionBoundaryType
)
from btc_service import BTCService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def format_btc(amount):
    """Format a BTC amount nicely"""
    if amount is None:
        return "???"
    return f"{float(amount):.8f} BTC"


def print_trace_entry(entry, verbose=False):
    """Print a single trace entry"""
    hop = entry.get('hop_number', '?')
    txid = entry.get('txid', 'unknown')[:16] + '...'
    vout = entry.get('vout', '?')
    amount = format_btc(entry.get('amount'))
    block = entry.get('block_height', '?')
    addr = entry.get('source_address', 'unknown')
    
    # Status indicators
    status = ""
    if entry.get('is_coinbase'):
        status = " ⛏️  [COINBASE - Mining Reward]"
    elif entry.get('is_exchange_like'):
        status = " 🏦 [EXCHANGE-LIKE]"
    elif entry.get('termination_reason') == 'MAX_HOPS':
        status = " ⏹️  [MAX HOPS REACHED]"
    elif entry.get('termination_reason') == 'MAX_TRANSACTIONS':
        status = " 🛑 [MAX TRANSACTIONS LIMIT]"
    elif entry.get('termination_reason') == 'ERROR':
        status = f" ❌ [ERROR: {entry.get('error', 'unknown')}]"
    
    print(f"  Hop {hop}: {txid}:{vout} | {amount} | Block {block}{status}")
    
    if verbose:
        print(f"         Address: {addr}")
        print(f"         Inputs: {entry.get('input_count', '?')} | Outputs: {entry.get('output_count', '?')}")
        if entry.get('exchange_indicators'):
            indicators = entry['exchange_indicators']
            print(f"         Exchange indicators: {json.dumps(indicators, default=str)}")
        if entry.get('block_time'):
            print(f"         Time: {entry['block_time']}")


def print_trace_summary(traces):
    """Print a summary of all traces"""
    total_utxos = len(traces)
    coinbase_count = 0
    exchange_count = 0
    max_hops_count = 0
    max_tx_count = 0
    error_count = 0
    total_hops = 0
    
    for utxo_key, trace in traces.items():
        total_hops += len(trace)
        for entry in trace:
            if entry.get('is_coinbase'):
                coinbase_count += 1
            elif entry.get('is_exchange_like'):
                exchange_count += 1
            elif entry.get('termination_reason') == 'MAX_HOPS':
                max_hops_count += 1
            elif entry.get('termination_reason') == 'MAX_TRANSACTIONS':
                max_tx_count += 1
            elif entry.get('termination_reason') == 'ERROR':
                error_count += 1
    
    print("\n" + "=" * 60)
    print("TRACE SUMMARY")
    print("=" * 60)
    print(f"Total UTXOs traced: {total_utxos}")
    print(f"Total hops explored: {total_hops}")
    print(f"Reached coinbase (mining): {coinbase_count}")
    print(f"Reached exchange-like tx: {exchange_count}")
    print(f"Stopped at max hops: {max_hops_count}")
    print(f"Stopped at max transactions: {max_tx_count}")
    print(f"Errors encountered: {error_count}")


def save_traces_to_db(db, utxo_id, traces):
    """Save trace results to legacy trace history table"""
    saved_count = 0
    
    for entry in traces:
        # Map termination reason
        termination = None
        if entry.get('termination_reason'):
            try:
                termination = TraceTerminationReason[entry['termination_reason']]
            except KeyError:
                termination = TraceTerminationReason.ERROR
        
        # Check if entry already exists
        existing = db.query(BTCUTXOTraceHistory).filter(
            BTCUTXOTraceHistory.root_utxo_id == utxo_id,
            BTCUTXOTraceHistory.hop_number == entry.get('hop_number'),
            BTCUTXOTraceHistory.txid == entry.get('txid'),
            BTCUTXOTraceHistory.vout == entry.get('vout')
        ).first()
        
        if existing:
            logger.debug(f"Trace entry already exists for hop {entry.get('hop_number')}")
            continue
        
        # Create new trace entry
        trace_entry = BTCUTXOTraceHistory(
            root_utxo_id=utxo_id,
            hop_number=entry.get('hop_number', 0),
            txid=entry.get('txid'),
            vout=entry.get('vout', 0),
            amount=entry.get('amount', Decimal('0')),
            block_height=entry.get('block_height'),
            block_time=entry.get('block_time'),
            source_address=entry.get('source_address'),
            input_count=entry.get('input_count'),
            output_count=entry.get('output_count'),
            is_coinbase=entry.get('is_coinbase', False),
            is_exchange_like=entry.get('is_exchange_like', False),
            exchange_indicators=json.dumps(entry.get('exchange_indicators', {})),
            termination_reason=termination
        )
        
        db.add(trace_entry)
        saved_count += 1
    
    return saved_count


def get_or_create_traced_transaction(db, entry):
    """Get or create a traced transaction record"""
    txid = entry.get('txid')
    if not txid:
        return None
    
    # Check if exists
    tx = db.query(BTCTracedTransaction).filter(
        BTCTracedTransaction.txid == txid
    ).first()
    
    if tx:
        return tx
    
    # Determine boundary type
    boundary = TransactionBoundaryType.NONE
    if entry.get('is_coinbase'):
        boundary = TransactionBoundaryType.COINBASE
    elif entry.get('is_exchange_like'):
        boundary = TransactionBoundaryType.EXCHANGE
    
    # Create new
    tx = BTCTracedTransaction(
        txid=txid,
        block_height=entry.get('block_height'),
        block_time=entry.get('block_time'),
        input_count=entry.get('input_count'),
        output_count=entry.get('output_count'),
        is_coinbase=entry.get('is_coinbase', False),
        is_exchange_like=entry.get('is_exchange_like', False),
        boundary_type=boundary,
        exchange_indicators=json.dumps(entry.get('exchange_indicators', {})) if entry.get('exchange_indicators') else None
    )
    db.add(tx)
    db.flush()  # Get the ID
    
    return tx


def get_or_create_traced_address(db, address, block_height=None):
    """Get or create a traced address record"""
    if not address:
        return None
    
    # Check if exists
    addr = db.query(BTCTracedAddress).filter(
        BTCTracedAddress.address == address
    ).first()
    
    if addr:
        # Update block range
        if block_height:
            if addr.first_seen_block is None or block_height < addr.first_seen_block:
                addr.first_seen_block = block_height
            if addr.last_seen_block is None or block_height > addr.last_seen_block:
                addr.last_seen_block = block_height
        return addr
    
    # Check if this is a monitored address
    monitoring = db.query(BTCAddressMonitoring).filter(
        BTCAddressMonitoring.bitcoin_address == address
    ).first()
    
    # Create new
    addr = BTCTracedAddress(
        address=address,
        is_monitored=monitoring is not None,
        monitoring_id=monitoring.id if monitoring else None,
        first_seen_block=block_height,
        last_seen_block=block_height
    )
    db.add(addr)
    db.flush()
    
    return addr


def save_to_graph_tables(db, traces):
    """Save trace results to graph tables (deduplicated)"""
    tx_count = 0
    addr_count = 0
    flow_count = 0
    
    # First pass: create all transactions and addresses
    tx_map = {}  # txid -> BTCTracedTransaction
    
    for entry in traces:
        txid = entry.get('txid')
        if not txid or txid in tx_map:
            continue
        
        tx = get_or_create_traced_transaction(db, entry)
        if tx:
            tx_map[txid] = tx
            tx_count += 1
        
        # Create address record
        source_addr = entry.get('source_address')
        if source_addr:
            addr = get_or_create_traced_address(db, source_addr, entry.get('block_height'))
            if addr:
                addr_count += 1
    
    # Second pass: create flows (spending relationships)
    for entry in traces:
        # Check if this entry was spent by another transaction
        spent_by_txid = entry.get('spent_by_txid')
        spent_by_vin = entry.get('spent_by_vin')
        
        if spent_by_txid is None or spent_by_vin is None:
            continue
        
        from_txid = entry.get('txid')
        from_vout = entry.get('vout')
        
        if from_txid is None or from_vout is None:
            continue
        
        # Get transaction records
        from_tx = tx_map.get(from_txid)
        to_tx = tx_map.get(spent_by_txid)
        
        if not from_tx or not to_tx:
            # Try to get from database
            from_tx = from_tx or db.query(BTCTracedTransaction).filter(
                BTCTracedTransaction.txid == from_txid
            ).first()
            to_tx = to_tx or db.query(BTCTracedTransaction).filter(
                BTCTracedTransaction.txid == spent_by_txid
            ).first()
        
        if not from_tx or not to_tx:
            continue
        
        # Get address records
        from_addr = None
        source_address = entry.get('source_address')
        if source_address:
            from_addr = db.query(BTCTracedAddress).filter(
                BTCTracedAddress.address == source_address
            ).first()
        
        # Check if flow already exists
        existing_flow = db.query(BTCTransactionFlow).filter(
            BTCTransactionFlow.from_txid_id == from_tx.id,
            BTCTransactionFlow.from_vout == from_vout,
            BTCTransactionFlow.to_txid_id == to_tx.id,
            BTCTransactionFlow.to_vin == spent_by_vin
        ).first()
        
        if existing_flow:
            continue
        
        # Create flow
        flow = BTCTransactionFlow(
            from_txid_id=from_tx.id,
            from_vout=from_vout,
            to_txid_id=to_tx.id,
            to_vin=spent_by_vin,
            amount=entry.get('amount', Decimal('0')),
            from_address_id=from_addr.id if from_addr else None
        )
        db.add(flow)
        flow_count += 1
    
    return tx_count, addr_count, flow_count


def clear_trace_data(db):
    """Clear all trace data from database"""
    print("\n🗑️  Clearing existing trace data...")
    
    # Clear in order due to foreign keys
    flow_count = db.query(BTCTransactionFlow).delete()
    print(f"  Deleted {flow_count} transaction flows")
    
    addr_count = db.query(BTCTracedAddress).delete()
    print(f"  Deleted {addr_count} traced addresses")
    
    tx_count = db.query(BTCTracedTransaction).delete()
    print(f"  Deleted {tx_count} traced transactions")
    
    trace_count = db.query(BTCUTXOTraceHistory).delete()
    print(f"  Deleted {trace_count} trace history entries")
    
    db.commit()
    print("✓ Trace data cleared")


def trace_single_address(db, btc_service, address, args):
    """Trace a single address and return results"""
    monitoring = db.query(BTCAddressMonitoring).filter(
        BTCAddressMonitoring.bitcoin_address == address
    ).first()
    
    if not monitoring:
        print(f"\n⚠️  Warning: Address {address} is not in monitored addresses")
        print("   Proceeding with blockchain query only...")
        db_utxos = []
    else:
        print(f"\n✓ Found in monitored addresses")
        print(f"  Source: {monitoring.source_label}")
        print(f"  Status: {monitoring.monitor_status}")
        print(f"  Last known balance: {format_btc(monitoring.last_known_balance)}")
        
        # Get UTXOs from database
        db_utxos = db.query(BTCAddressUTXO).filter(
            BTCAddressUTXO.bitcoin_address == address,
            BTCAddressUTXO.spent_in_tx.is_(None)  # Only unspent
        ).all()
        
        print(f"  UTXOs in database: {len(db_utxos)}")
    
    # Decide which UTXOs to use - DATABASE by default, watch wallet if flag is set
    if args.use_watch_wallet or not db_utxos:
        if args.use_watch_wallet:
            print("\n🔍 Querying Bitcoin Core watch wallet for UTXOs...")
        else:
            print("\n🔍 No UTXOs in database, querying Bitcoin Core watch wallet...")
        
        try:
            btc_service.load_watch_wallet()
        except Exception as e:
            if "is already loaded" not in str(e):
                logger.warning(f"Could not load wallet: {e}")
        
        blockchain_utxos, total = btc_service.check_address_utxos(address)
        print(f"  Found {len(blockchain_utxos)} UTXOs totaling {format_btc(total)}")
        
        utxos_to_trace = []
        for u in blockchain_utxos:
            utxo_data = {
                'txid': u.get('txid'),
                'vout': u.get('vout'),
                'amount': u.get('amount', 0)
            }
            # Try to find matching DB UTXO for ID
            for db_u in db_utxos:
                if db_u.txid == u.get('txid') and db_u.vout == u.get('vout'):
                    utxo_data['db_id'] = db_u.id
                    break
            utxos_to_trace.append(utxo_data)
    else:
        print("\n📋 Using UTXOs from database (default):")
        utxos_to_trace = [
            {'txid': u.txid, 'vout': u.vout, 'amount': float(u.amount), 'db_id': u.id}
            for u in db_utxos
        ]
    
    if not utxos_to_trace:
        print("  No UTXOs found to trace!")
        return {}
    
    # Display UTXOs to trace
    print(f"\n📍 UTXOs to trace ({len(utxos_to_trace)}):")
    for i, utxo in enumerate(utxos_to_trace, 1):
        txid_short = utxo['txid'][:16] + '...'
        amount = format_btc(utxo['amount'])
        db_id = utxo.get('db_id', 'N/A')
        print(f"  {i}. {txid_short}:{utxo['vout']} | {amount} | DB ID: {db_id}")
    
    # Trace each UTXO
    all_traces = {}
    total_saved = 0
    total_tx = 0
    total_addr = 0
    total_flow = 0
    
    for i, utxo in enumerate(utxos_to_trace, 1):
        utxo_key = f"{utxo['txid']}:{utxo['vout']}"
        print(f"\n{'─' * 60}")
        print(f"Tracing UTXO {i}/{len(utxos_to_trace)}: {utxo_key[:30]}...")
        print(f"{'─' * 60}")
        
        # Perform the trace
        traces = btc_service.trace_utxo_backwards(
            utxo['txid'], 
            utxo['vout'],
            max_hops=args.max_hops,
            max_transactions=args.max_transactions
        )
        
        all_traces[utxo_key] = traces
        
        # Display trace results
        if not traces:
            print("  No trace results!")
            continue
        
        # Group by termination point for cleaner display
        terminal_entries = [e for e in traces if e.get('termination_reason')]
        intermediate_entries = [e for e in traces if not e.get('termination_reason')]
        
        # Show all entries if verbose, otherwise just terminal ones
        entries_to_show = traces if args.verbose else terminal_entries
        
        print(f"\n  Trace results ({len(traces)} total hops, {len(terminal_entries)} endpoints):")
        
        for entry in entries_to_show:
            print_trace_entry(entry, verbose=args.verbose)
        
        if not args.verbose and intermediate_entries:
            print(f"\n  (Use --verbose to see all {len(intermediate_entries)} intermediate hops)")
        
        # Save to database if requested
        if args.save:
            # Save to legacy trace history table
            if utxo.get('db_id'):
                saved = save_traces_to_db(db, utxo['db_id'], traces)
                total_saved += saved
                if saved > 0:
                    print(f"\n  💾 Saved {saved} trace entries to history table")
            
            # Save to graph tables
            tx_count, addr_count, flow_count = save_to_graph_tables(db, traces)
            total_tx += tx_count
            total_addr += addr_count
            total_flow += flow_count
            if tx_count > 0 or flow_count > 0:
                print(f"  📊 Graph: {tx_count} transactions, {addr_count} addresses, {flow_count} flows")
    
    return all_traces


def main():
    parser = argparse.ArgumentParser(
        description='Trace UTXO history backwards to find origins (coinbase/exchange)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('address', nargs='?', help='Bitcoin address to trace (or use --all)')
    parser.add_argument('--all', action='store_true',
                        help='Trace ALL monitored addresses')
    parser.add_argument('--clear', action='store_true',
                        help='Clear existing trace data before starting')
    parser.add_argument('--max-hops', type=int, default=10, 
                        help='Maximum depth per trace branch (default: 10)')
    parser.add_argument('--max-transactions', type=int, default=100,
                        help='Maximum total transactions to explore per UTXO (default: 100)')
    parser.add_argument('--save', action='store_true',
                        help='Save trace results to database (includes graph tables)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed output for each hop')
    parser.add_argument('--use-watch-wallet', action='store_true',
                        help='Query Bitcoin Core watch wallet instead of using database UTXOs')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.address and not args.all:
        parser.error("Either provide an address or use --all")
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    print("=" * 60)
    print("UTXO HISTORY TRACER")
    print("=" * 60)
    if args.all:
        print("Mode: ALL monitored addresses")
    else:
        print(f"Address: {args.address.strip()}")
    print(f"Max hops: {args.max_hops}")
    print(f"Max transactions: {args.max_transactions}")
    print(f"Save to DB: {args.save}")
    print(f"Clear first: {args.clear}")
    print(f"UTXO source: {'Watch wallet (blockchain)' if args.use_watch_wallet else 'Database'}")
    print("=" * 60)
    
    # Initialize BTC service
    btc_service = BTCService(test_connection=True)
    if not btc_service.is_available:
        print("\n❌ ERROR: Bitcoin Core RPC is not available!")
        print("Make sure Bitcoin Core is running and RPC is configured.")
        sys.exit(1)
    
    print("\n✓ Connected to Bitcoin Core")
    
    db = SessionLocal()
    try:
        # Clear data if requested
        if args.clear:
            clear_trace_data(db)
        
        # Get addresses to trace
        if args.all:
            # Get all active monitored addresses
            monitored = db.query(BTCAddressMonitoring).filter(
                BTCAddressMonitoring.monitor_status == 'active'
            ).all()
            
            if not monitored:
                print("\n❌ No active monitored addresses found!")
                sys.exit(1)
            
            addresses = [m.bitcoin_address for m in monitored]
            print(f"\n📋 Found {len(addresses)} active monitored addresses")
        else:
            addresses = [args.address.strip()]
        
        # Trace each address
        all_results = {}
        for i, address in enumerate(addresses, 1):
            print(f"\n{'=' * 60}")
            print(f"ADDRESS {i}/{len(addresses)}: {address}")
            print(f"{'=' * 60}")
            
            traces = trace_single_address(db, btc_service, address, args)
            all_results.update(traces)
        
        # Commit if we saved anything
        if args.save:
            db.commit()
            print(f"\n✓ All changes committed to database")
            
            # Print graph statistics
            tx_count = db.query(BTCTracedTransaction).count()
            addr_count = db.query(BTCTracedAddress).count()
            flow_count = db.query(BTCTransactionFlow).count()
            
            print(f"\n📊 Graph Database Statistics:")
            print(f"  Transactions: {tx_count}")
            print(f"  Addresses: {addr_count}")
            print(f"  Flows: {flow_count}")
        
        # Print summary
        print_trace_summary(all_results)
        
    except Exception as e:
        logger.exception("Error during trace")
        print(f"\n❌ Error: {e}")
        if args.save:
            db.rollback()
        sys.exit(1)
    
    finally:
        db.close()
    
    print("\n✓ Trace complete!")


if __name__ == "__main__":
    main()
