#!/usr/bin/env python3
"""
Neo4j Graph Exporter

Exports the traced UTXO history graph to Neo4j Cypher statements for visualization.

Usage:
    python export_neo4j_graph.py [--output FILE] [--format FORMAT]

Options:
    --output FILE       Output file (default: btc_graph.cypher)
    --format FORMAT     Output format: cypher, json (default: cypher)
    --include-amounts   Include BTC amounts as properties
    --monitored-only    Only export subgraph connected to monitored addresses

Examples:
    python export_neo4j_graph.py
    python export_neo4j_graph.py --output my_graph.cypher --include-amounts
    python export_neo4j_graph.py --format json --output graph.json
"""

import argparse
import json
import sys
import logging
from datetime import datetime
from decimal import Decimal

from db_config import SessionLocal
from models import (
    BTCTracedTransaction, BTCTracedAddress, BTCTransactionFlow,
    BTCAddressMonitoring, BTCUTXOTraceHistory, TransactionBoundaryType
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def escape_cypher_string(s):
    """Escape a string for use in Cypher"""
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


def generate_cypher_export(db, include_amounts=True, monitored_only=False):
    """Generate Cypher statements for Neo4j import"""
    lines = []
    
    # Header
    lines.append("// Neo4j Cypher export of BTC UTXO trace graph")
    lines.append(f"// Generated: {datetime.now().isoformat()}")
    lines.append("// ")
    lines.append("// Run this in Neo4j Browser or with cypher-shell")
    lines.append("// ")
    lines.append("")
    
    # Clear existing data (optional)
    lines.append("// Uncomment to clear existing data:")
    lines.append("// MATCH (n) DETACH DELETE n;")
    lines.append("")
    
    # Create constraints/indexes
    lines.append("// Create constraints and indexes")
    lines.append("CREATE CONSTRAINT tx_txid IF NOT EXISTS FOR (t:Transaction) REQUIRE t.txid IS UNIQUE;")
    lines.append("CREATE CONSTRAINT addr_address IF NOT EXISTS FOR (a:Address) REQUIRE a.address IS UNIQUE;")
    lines.append("CREATE INDEX tx_boundary IF NOT EXISTS FOR (t:Transaction) ON (t.boundary_type);")
    lines.append("CREATE INDEX addr_monitored IF NOT EXISTS FOR (a:Address) ON (a.is_monitored);")
    lines.append("")
    
    # Get all transactions
    transactions = db.query(BTCTracedTransaction).all()
    
    # Get all addresses
    addresses = db.query(BTCTracedAddress).all()
    
    # Get all flows
    flows = db.query(BTCTransactionFlow).all()
    
    logger.info(f"Exporting {len(transactions)} transactions, {len(addresses)} addresses, {len(flows)} flows")
    
    # Create Transaction nodes
    lines.append("// Create Transaction nodes")
    lines.append("// ========================")
    
    for tx in transactions:
        # Determine labels
        labels = ["Transaction"]
        if tx.is_coinbase:
            labels.append("Coinbase")
        if tx.is_exchange_like:
            labels.append("Exchange")
        
        label_str = ":".join(labels)
        
        # Build properties
        props = {
            "txid": tx.txid,
            "block_height": tx.block_height,
            "input_count": tx.input_count,
            "output_count": tx.output_count,
            "is_coinbase": tx.is_coinbase,
            "is_exchange": tx.is_exchange_like,
            "boundary_type": tx.boundary_type.value if tx.boundary_type else "NONE"
        }
        
        if tx.block_time:
            props["block_time"] = tx.block_time.isoformat()
        
        # Format properties for Cypher
        prop_parts = []
        for k, v in props.items():
            if v is None:
                continue
            if isinstance(v, bool):
                prop_parts.append(f"{k}: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                prop_parts.append(f"{k}: {v}")
            else:
                prop_parts.append(f"{k}: '{escape_cypher_string(v)}'")
        
        prop_str = ", ".join(prop_parts)
        lines.append(f"MERGE (:{label_str} {{{prop_str}}});")
    
    lines.append("")
    
    # Create Address nodes
    lines.append("// Create Address nodes")
    lines.append("// ====================")
    
    for addr in addresses:
        # Determine labels
        labels = ["Address"]
        if addr.is_monitored:
            labels.append("Monitored")
        if addr.is_exchange_address:
            labels.append("Exchange")
        
        label_str = ":".join(labels)
        
        # Build properties
        props = {
            "address": addr.address,
            "is_monitored": addr.is_monitored,
            "is_exchange": addr.is_exchange_address
        }
        
        if addr.first_seen_block:
            props["first_seen_block"] = addr.first_seen_block
        if addr.last_seen_block:
            props["last_seen_block"] = addr.last_seen_block
        if include_amounts:
            if addr.total_received:
                props["total_received"] = float(addr.total_received)
            if addr.total_sent:
                props["total_sent"] = float(addr.total_sent)
        
        # Format properties for Cypher
        prop_parts = []
        for k, v in props.items():
            if v is None:
                continue
            if isinstance(v, bool):
                prop_parts.append(f"{k}: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                prop_parts.append(f"{k}: {v}")
            else:
                prop_parts.append(f"{k}: '{escape_cypher_string(v)}'")
        
        prop_str = ", ".join(prop_parts)
        lines.append(f"MERGE (:{label_str} {{{prop_str}}});")
    
    lines.append("")
    
    # Create FUNDED_BY relationships (transaction to transaction)
    lines.append("// Create FUNDED_BY relationships")
    lines.append("// ===============================")
    lines.append("// Direction: (spending_tx)-[:FUNDED_BY]->(funding_tx)")
    lines.append("// Meaning: spending_tx was funded by an output from funding_tx")
    lines.append("")
    
    # Build lookup for txid -> txid
    tx_lookup = {tx.id: tx.txid for tx in transactions}
    
    for flow in flows:
        from_txid = tx_lookup.get(flow.from_txid_id)
        to_txid = tx_lookup.get(flow.to_txid_id)
        
        if not from_txid or not to_txid:
            continue
        
        # Properties for the relationship
        props = {
            "vout": flow.from_vout,
            "vin": flow.to_vin
        }
        
        if include_amounts and flow.amount:
            props["amount"] = float(flow.amount)
        
        prop_parts = []
        for k, v in props.items():
            if isinstance(v, (int, float)):
                prop_parts.append(f"{k}: {v}")
            else:
                prop_parts.append(f"{k}: '{escape_cypher_string(v)}'")
        
        prop_str = ", ".join(prop_parts)
        
        # The spending transaction (to_txid) was FUNDED_BY the source transaction (from_txid)
        lines.append(f"MATCH (spending:Transaction {{txid: '{escape_cypher_string(to_txid)}'}})")
        lines.append(f"MATCH (funding:Transaction {{txid: '{escape_cypher_string(from_txid)}'}})")
        lines.append(f"MERGE (spending)-[:FUNDED_BY {{{prop_str}}}]->(funding);")
        lines.append("")
    
    # Create ADDRESS relationships
    lines.append("// Create ADDRESS relationships")
    lines.append("// ============================")
    lines.append("// Links transactions to the addresses involved")
    lines.append("")
    
    addr_lookup = {addr.id: addr.address for addr in addresses}
    
    for flow in flows:
        if flow.from_address_id:
            from_addr = addr_lookup.get(flow.from_address_id)
            from_txid = tx_lookup.get(flow.from_txid_id)
            
            if from_addr and from_txid:
                lines.append(f"MATCH (t:Transaction {{txid: '{escape_cypher_string(from_txid)}'}})")
                lines.append(f"MATCH (a:Address {{address: '{escape_cypher_string(from_addr)}'}})")
                lines.append(f"MERGE (t)-[:OUTPUT_TO {{vout: {flow.from_vout}}}]->(a);")
                lines.append("")
    
    # Create relationships for ROOT UTXOs (hop 0) - these are current UTXOs at monitored addresses
    # They don't have spending flows yet, so we need to link them directly
    lines.append("// Create HOLDS relationships for root UTXOs (current unspent outputs)")
    lines.append("// =====================================================================")
    lines.append("// These are the UTXOs currently held by monitored addresses")
    lines.append("")
    
    # Get hop 0 entries from trace history - these are the root UTXOs
    root_traces = db.query(BTCUTXOTraceHistory).filter(
        BTCUTXOTraceHistory.hop_number == 0,
        BTCUTXOTraceHistory.source_address.isnot(None)
    ).all()
    
    for trace in root_traces:
        if trace.source_address and trace.txid:
            lines.append(f"MATCH (t:Transaction {{txid: '{escape_cypher_string(trace.txid)}'}})")
            lines.append(f"MATCH (a:Address {{address: '{escape_cypher_string(trace.source_address)}'}})")
            lines.append(f"MERGE (t)-[:HOLDS {{vout: {trace.vout}, amount: {float(trace.amount) if trace.amount else 0}}}]->(a);")
            lines.append("")
    
    # Add helpful queries at the end
    lines.append("// ")
    lines.append("// Useful queries:")
    lines.append("// ")
    lines.append("// Show all monitored addresses and their current holdings:")
    lines.append("// MATCH (t:Transaction)-[:HOLDS]->(a:Monitored) RETURN a, t LIMIT 100;")
    lines.append("// ")
    lines.append("// Show monitored addresses with all connected transactions:")
    lines.append("// MATCH (a:Monitored)-[]-(t:Transaction) RETURN a, t LIMIT 100;")
    lines.append("// ")
    lines.append("// Find paths from monitored address back to exchange/coinbase:")
    lines.append("// MATCH (a:Monitored)<-[:HOLDS]-(t:Transaction)")
    lines.append("// MATCH p=(t)-[:FUNDED_BY*..10]->(boundary)")
    lines.append("// WHERE boundary:Coinbase OR boundary:Exchange")
    lines.append("// RETURN p LIMIT 20;")
    lines.append("// ")
    lines.append("// Find exchange boundaries:")
    lines.append("// MATCH (e:Exchange) RETURN e;")
    lines.append("// ")
    lines.append("// Show full transaction flow graph:")
    lines.append("// MATCH p=(:Transaction)-[:FUNDED_BY*..5]->(:Transaction) RETURN p LIMIT 50;")
    lines.append("// ")
    lines.append("// Find all paths for a specific monitored address:")
    lines.append("// MATCH (a:Address {address: 'bc1q...'})<-[:HOLDS]-(t:Transaction)")
    lines.append("// MATCH p=(t)-[:FUNDED_BY*..10]->(boundary)")
    lines.append("// WHERE boundary:Coinbase OR boundary:Exchange")
    lines.append("// RETURN p;")
    
    return "\n".join(lines)


def generate_json_export(db, include_amounts=True, monitored_only=False):
    """Generate JSON export for visualization tools"""
    
    # Get all data
    transactions = db.query(BTCTracedTransaction).all()
    addresses = db.query(BTCTracedAddress).all()
    flows = db.query(BTCTransactionFlow).all()
    
    # Build lookup tables
    tx_lookup = {tx.id: tx for tx in transactions}
    addr_lookup = {addr.id: addr for addr in addresses}
    
    # Build nodes
    nodes = []
    
    for tx in transactions:
        node = {
            "id": f"tx_{tx.txid[:16]}",
            "type": "transaction",
            "txid": tx.txid,
            "block_height": tx.block_height,
            "is_coinbase": tx.is_coinbase,
            "is_exchange": tx.is_exchange_like,
            "boundary_type": tx.boundary_type.value if tx.boundary_type else "NONE",
            "input_count": tx.input_count,
            "output_count": tx.output_count
        }
        if tx.block_time:
            node["block_time"] = tx.block_time.isoformat()
        nodes.append(node)
    
    for addr in addresses:
        node = {
            "id": f"addr_{addr.address[:16]}",
            "type": "address",
            "address": addr.address,
            "is_monitored": addr.is_monitored,
            "is_exchange": addr.is_exchange_address
        }
        if include_amounts:
            if addr.total_received:
                node["total_received"] = float(addr.total_received)
            if addr.total_sent:
                node["total_sent"] = float(addr.total_sent)
        nodes.append(node)
    
    # Build edges
    edges = []
    
    for flow in flows:
        from_tx = tx_lookup.get(flow.from_txid_id)
        to_tx = tx_lookup.get(flow.to_txid_id)
        
        if from_tx and to_tx:
            edge = {
                "source": f"tx_{to_tx.txid[:16]}",  # spending tx
                "target": f"tx_{from_tx.txid[:16]}",  # funding tx
                "type": "FUNDED_BY",
                "vout": flow.from_vout,
                "vin": flow.to_vin
            }
            if include_amounts and flow.amount:
                edge["amount"] = float(flow.amount)
            edges.append(edge)
        
        # Address relationships
        if flow.from_address_id and from_tx:
            from_addr = addr_lookup.get(flow.from_address_id)
            if from_addr:
                edges.append({
                    "source": f"tx_{from_tx.txid[:16]}",
                    "target": f"addr_{from_addr.address[:16]}",
                    "type": "OUTPUT_TO",
                    "vout": flow.from_vout
                })
    
    # Add HOLDS relationships for root UTXOs (hop 0)
    root_traces = db.query(BTCUTXOTraceHistory).filter(
        BTCUTXOTraceHistory.hop_number == 0,
        BTCUTXOTraceHistory.source_address.isnot(None)
    ).all()
    
    for trace in root_traces:
        if trace.source_address and trace.txid:
            edge = {
                "source": f"tx_{trace.txid[:16]}",
                "target": f"addr_{trace.source_address[:16]}",
                "type": "HOLDS",
                "vout": trace.vout
            }
            if include_amounts and trace.amount:
                edge["amount"] = float(trace.amount)
            edges.append(edge)
    
    result = {
        "metadata": {
            "generated": datetime.now().isoformat(),
            "transaction_count": len(transactions),
            "address_count": len(addresses),
            "flow_count": len(flows)
        },
        "nodes": nodes,
        "edges": edges
    }
    
    return json.dumps(result, indent=2, cls=DecimalEncoder)


def main():
    parser = argparse.ArgumentParser(
        description='Export UTXO trace graph to Neo4j Cypher or JSON',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--output', '-o', default='btc_graph.cypher',
                        help='Output file (default: btc_graph.cypher)')
    parser.add_argument('--format', '-f', choices=['cypher', 'json'], default='cypher',
                        help='Output format (default: cypher)')
    parser.add_argument('--include-amounts', action='store_true', default=True,
                        help='Include BTC amounts as properties (default: true)')
    parser.add_argument('--no-amounts', action='store_true',
                        help='Exclude BTC amounts from export')
    parser.add_argument('--monitored-only', action='store_true',
                        help='Only export subgraph connected to monitored addresses')
    
    args = parser.parse_args()
    
    include_amounts = not args.no_amounts
    
    print("=" * 60)
    print("NEO4J GRAPH EXPORTER")
    print("=" * 60)
    print(f"Output file: {args.output}")
    print(f"Format: {args.format}")
    print(f"Include amounts: {include_amounts}")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        # Check if we have data
        tx_count = db.query(BTCTracedTransaction).count()
        addr_count = db.query(BTCTracedAddress).count()
        flow_count = db.query(BTCTransactionFlow).count()
        
        print(f"\n📊 Graph data available:")
        print(f"  Transactions: {tx_count}")
        print(f"  Addresses: {addr_count}")
        print(f"  Flows: {flow_count}")
        
        if tx_count == 0:
            print("\n⚠️  No trace data found!")
            print("   Run: python trace_utxo_history.py --all --save")
            sys.exit(1)
        
        # Generate export
        print(f"\n📝 Generating {args.format} export...")
        
        if args.format == 'cypher':
            content = generate_cypher_export(db, include_amounts, args.monitored_only)
        else:
            content = generate_json_export(db, include_amounts, args.monitored_only)
        
        # Write to file
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"\n✓ Exported to {args.output}")
        print(f"  File size: {len(content):,} bytes")
        
        if args.format == 'cypher':
            print("\n📌 To import into Neo4j:")
            print(f"   1. Open Neo4j Browser")
            print(f"   2. Copy contents of {args.output}")
            print(f"   3. Paste and run in Neo4j Browser")
            print(f"   Or use: cat {args.output} | cypher-shell -u neo4j -p <password>")
        
    except Exception as e:
        logger.exception("Error during export")
        print(f"\n❌ Error: {e}")
        sys.exit(1)
    
    finally:
        db.close()
    
    print("\n✓ Export complete!")


if __name__ == "__main__":
    main()
