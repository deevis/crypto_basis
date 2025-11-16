"""
Query and display OP_RETURN data from the database
"""
import argparse
import json
import base64
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from db_config import SessionLocal
from models import OPReturnScan, LargeOPReturn
from sqlalchemy import func, desc

def show_statistics():
    """Show overall statistics"""
    db = SessionLocal()
    
    stats = db.query(
        func.count(OPReturnScan.id).label('total_blocks'),
        func.sum(OPReturnScan.large_op_returns_found).label('total_ops'),
        func.min(OPReturnScan.block_number).label('first_block'),
        func.max(OPReturnScan.block_number).label('last_block')
    ).first()
    
    print("\n[STATS] OP_RETURN Scan Statistics")
    print("=" * 60)
    print(f"Total blocks scanned:      {stats.total_blocks or 0}")
    print(f"Total large OP_RETURNs:    {stats.total_ops or 0}")
    
    if stats.first_block:
        # Get the actual dates for first and last blocks
        first_scan = db.query(OPReturnScan).filter(
            OPReturnScan.block_number == stats.first_block
        ).first()
        last_scan = db.query(OPReturnScan).filter(
            OPReturnScan.block_number == stats.last_block
        ).first()
        
        print(f"\nBlock range:               {stats.first_block} - {stats.last_block}")
        if first_scan and last_scan:
            print(f"Date range:                {first_scan.block_time.strftime('%Y-%m-%d %H:%M:%S')} to")
            print(f"                           {last_scan.block_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Get mining pool breakdown
    print("\n[MINERS] Mining Pool Breakdown:")
    mining_pools = db.query(
        OPReturnScan.mined_by,
        func.count(OPReturnScan.id).label('count'),
        func.sum(OPReturnScan.large_op_returns_found).label('total_ops')
    ).group_by(OPReturnScan.mined_by).order_by(desc('count')).all()
    
    for pool, count, ops in mining_pools:
        pool_name = pool or 'Unknown'
        print(f"   {pool_name:.<25} {count:>4} blocks, {ops or 0:>4} OP_RETURNs")
    
    # Get file type breakdown
    print("\n[FILES] File Type Breakdown:")
    file_types = db.query(
        LargeOPReturn.file_type,
        func.count(LargeOPReturn.id).label('count')
    ).group_by(LargeOPReturn.file_type).order_by(desc('count')).all()
    
    for ft, count in file_types:
        print(f"   {ft or 'unknown':.<20} {count:>5}")
    
    # Get size histogram
    print("\n[SIZES] OP_RETURN Size Distribution:")
    all_sizes = db.query(LargeOPReturn.data_size).all()
    
    size_ranges = {
        '84-200 bytes': (84, 200),
        '200-1K bytes': (201, 1023),
        '1K-10K bytes': (1024, 10239),
        '10K-50K bytes': (10240, 51199),
        '50K-100K bytes': (51200, 102400)
    }
    
    size_counts = {label: 0 for label in size_ranges.keys()}
    max_count = 0
    
    for (size,) in all_sizes:
        for label, (min_size, max_size) in size_ranges.items():
            if min_size <= size <= max_size:
                size_counts[label] += 1
                max_count = max(max_count, size_counts[label])
                break
    
    # Display histogram with bar graph
    for label in size_ranges.keys():
        count = size_counts[label]
        if max_count > 0:
            bar_length = int((count / max_count) * 40)
            bar = '#' * bar_length
        else:
            bar = ''
        print(f"   {label:.<20} {count:>5}  {bar}")
    
    # Get fee statistics (only for entries with fee data)
    print("\n[FEES] Transaction Fee Statistics:")
    fee_stats = db.query(
        func.count(LargeOPReturn.id).label('count'),
        func.sum(LargeOPReturn.tx_fee).label('total_fees'),
        func.avg(LargeOPReturn.tx_fee).label('avg_fee'),
        func.avg(LargeOPReturn.fee_rate).label('avg_fee_rate'),
        func.avg(LargeOPReturn.cost_per_byte).label('avg_cost_per_byte'),
        func.min(LargeOPReturn.fee_rate).label('min_fee_rate'),
        func.max(LargeOPReturn.fee_rate).label('max_fee_rate')
    ).filter(LargeOPReturn.tx_fee.isnot(None)).first()
    
    if fee_stats.count and fee_stats.count > 0:
        print(f"   Transactions with fee data: {fee_stats.count}")
        print(f"   Total fees paid:            {fee_stats.total_fees:,.0f} sats ({fee_stats.total_fees / 100000000:.8f} BTC)")
        print(f"   Average fee:                {fee_stats.avg_fee:,.0f} sats")
        print(f"   Average fee rate:           {fee_stats.avg_fee_rate:.2f} sats/vbyte")
        print(f"   Fee rate range:             {fee_stats.min_fee_rate:.2f} - {fee_stats.max_fee_rate:.2f} sats/vbyte")
        print(f"   Avg cost per byte of data:  {fee_stats.avg_cost_per_byte:.2f} sats/byte")
    else:
        print("   No fee data available yet")
    
    # Get monthly breakdown (only months with large OP_RETURNs)
    print("\n[MONTHLY] Large OP_RETURN Activity by Month:")
    
    # Get all scans with large OP_RETURNs
    scans_with_ops = db.query(OPReturnScan).filter(
        OPReturnScan.large_op_returns_found > 0
    ).order_by(OPReturnScan.block_time).all()
    
    if scans_with_ops:
        # Group by month in Python
        from collections import defaultdict
        monthly_stats = defaultdict(lambda: {'blocks': 0, 'op_returns': 0})
        
        for scan in scans_with_ops:
            month_key = scan.block_time.strftime('%Y-%m')
            monthly_stats[month_key]['blocks'] += 1
            monthly_stats[month_key]['op_returns'] += scan.large_op_returns_found
        
        # Sort by month and display
        max_ops = max(stats['op_returns'] for stats in monthly_stats.values())
        for month in sorted(monthly_stats.keys()):
            stats = monthly_stats[month]
            # Create a simple bar graph
            bar_length = int((stats['op_returns'] / max_ops) * 30) if max_ops > 0 else 0
            bar = '#' * bar_length
            print(f"   {month}.......... {stats['op_returns']:>4} OP_RETURNs in {stats['blocks']:>3} blocks  {bar}")
    else:
        print("   No activity yet")
    
    db.close()

def list_blocks(limit=10):
    """List blocks with large OP_RETURNs"""
    db = SessionLocal()
    
    blocks = db.query(OPReturnScan).order_by(desc(OPReturnScan.block_number)).limit(limit).all()
    
    print(f"\n[BLOCKS] Recent Blocks with Large OP_RETURNs (showing last {limit})")
    print("=" * 100)
    print(f"{'Block':>8} {'Date':>20} {'Mined By':<20} {'Txs':>6} {'OP_RETURNs':>10}")
    print("-" * 100)
    
    for block in blocks:
        miner = (block.mined_by or 'Unknown')[:19]  # Truncate to fit
        print(f"{block.block_number:>8} {block.block_time.strftime('%Y-%m-%d %H:%M:%S'):>20} "
              f"{miner:<20} {block.total_transactions:>6} {block.large_op_returns_found:>10}")
    
    db.close()

def show_block_details(block_number):
    """Show details for a specific block"""
    db = SessionLocal()
    
    scan = db.query(OPReturnScan).filter_by(block_number=block_number).first()
    
    if not scan:
        print(f"[ERROR] Block {block_number} not found in database")
        db.close()
        return
    
    print(f"\n[BLOCK] Block {block_number} Details")
    print("=" * 80)
    print(f"Block Hash:          {scan.block_hash}")
    print(f"Block Time:          {scan.block_time}")
    print(f"Mined By:            {scan.mined_by or 'Unknown'}")
    print(f"Total Transactions:  {scan.total_transactions}")
    print(f"Large OP_RETURNs:    {scan.large_op_returns_found}")
    print(f"Scanned At:          {scan.scanned_at}")
    
    if scan.coinbase_text:
        preview = scan.coinbase_text[:100]
        if len(scan.coinbase_text) > 100:
            preview += "..."
        print(f"Coinbase Text:       {preview}")
    
    if scan.large_op_returns_found > 0:
        print(f"\n[TRANSACTIONS] Large OP_RETURN Transactions:")
        print("-" * 80)
        
        for op in scan.op_returns:
            print(f"\nTransaction: {op.txid}")
            print(f"  Vout Index:    {op.vout_index}")
            print(f"  Data Size:     {op.data_size} bytes")
            print(f"  File Type:     {op.file_type}")
            print(f"  MIME Type:     {op.mime_type}")
            print(f"  Is Text:       {op.is_text}")
            
            # Show fee information if available
            if op.tx_fee:
                print(f"  TX Fee:        {op.tx_fee:,} sats")
                print(f"  TX Size:       {op.tx_size} vbytes")
                print(f"  Fee Rate:      {op.fee_rate:.2f} sats/vbyte")
                print(f"  Cost/Byte:     {op.cost_per_byte:.2f} sats per byte of OP_RETURN data")
                if op.tx_input_count:
                    print(f"  Inputs/Outputs: {op.tx_input_count} / {op.tx_output_count}")
            
            if op.is_text and op.decoded_text:
                preview = op.decoded_text[:200]
                if len(op.decoded_text) > 200:
                    preview += "..."
                print(f"  Text Preview:  {preview}")
    
    db.close()

def search_by_txid(txid):
    """Search for OP_RETURN by transaction ID"""
    db = SessionLocal()
    
    ops = db.query(LargeOPReturn).filter(LargeOPReturn.txid.like(f"%{txid}%")).all()
    
    if not ops:
        print(f"[NOTFOUND] No OP_RETURNs found matching txid: {txid}")
        db.close()
        return
    
    print(f"\n[SEARCH] Found {len(ops)} OP_RETURN(s) matching '{txid}'")
    print("=" * 80)
    
    for op in ops:
        print(f"\nBlock:         {op.block_number}")
        print(f"Transaction:   {op.txid}")
        print(f"Vout Index:    {op.vout_index}")
        print(f"Data Size:     {op.data_size} bytes")
        print(f"File Type:     {op.file_type}")
        print(f"Is Text:       {op.is_text}")
        
        if op.is_text and op.decoded_text:
            print(f"\nDecoded Text:")
            print("-" * 80)
            print(op.decoded_text)
    
    db.close()

def search_by_file_type(file_type):
    """Search for blocks with specific file types"""
    db = SessionLocal()
    
    # Get blocks that have OP_RETURNs with the specified file type
    results = db.query(
        OPReturnScan.block_number,
        OPReturnScan.block_time,
        OPReturnScan.mined_by,
        LargeOPReturn.txid,
        LargeOPReturn.data_size,
        LargeOPReturn.file_type
    ).join(
        LargeOPReturn, OPReturnScan.id == LargeOPReturn.scan_id
    ).filter(
        LargeOPReturn.file_type == file_type
    ).order_by(
        desc(OPReturnScan.block_number)
    ).all()
    
    if not results:
        print(f"[NOTFOUND] No OP_RETURNs found with file type: {file_type}")
        db.close()
        return
    
    print(f"\n[FILETYPE] Found {len(results)} OP_RETURN(s) with file type '{file_type}'")
    print("=" * 110)
    print(f"{'Block':>8} {'Date':>20} {'Mined By':<20} {'Size (bytes)':>12} {'Transaction ID':<64}")
    print("-" * 110)
    
    for block_num, block_time, mined_by, txid, size, ftype in results:
        miner = (mined_by or 'Unknown')[:19]
        print(f"{block_num:>8} {block_time.strftime('%Y-%m-%d %H:%M:%S'):>20} "
              f"{miner:<20} {size:>12} {txid}")
    
    db.close()

def search_by_size_range(min_size=None, max_size=None):
    """Search for OP_RETURNs within a size range"""
    db = SessionLocal()
    
    # Build query with size filters
    query = db.query(
        OPReturnScan.block_number,
        OPReturnScan.block_time,
        OPReturnScan.mined_by,
        LargeOPReturn.txid,
        LargeOPReturn.data_size,
        LargeOPReturn.file_type,
        LargeOPReturn.tx_fee,
        LargeOPReturn.fee_rate
    ).join(
        LargeOPReturn, OPReturnScan.id == LargeOPReturn.scan_id
    )
    
    # Apply filters
    if min_size is not None:
        query = query.filter(LargeOPReturn.data_size >= min_size)
    if max_size is not None:
        query = query.filter(LargeOPReturn.data_size <= max_size)
    
    results = query.order_by(
        desc(LargeOPReturn.data_size)
    ).all()
    
    if not results:
        size_desc = []
        if min_size is not None:
            size_desc.append(f">= {min_size:,} bytes")
        if max_size is not None:
            size_desc.append(f"<= {max_size:,} bytes")
        print(f"[NOTFOUND] No OP_RETURNs found with size {' and '.join(size_desc)}")
        db.close()
        return
    
    # Display header
    size_desc = []
    if min_size is not None:
        size_desc.append(f">= {min_size:,}")
    if max_size is not None:
        size_desc.append(f"<= {max_size:,}")
    
    print(f"\n[SIZE] Found {len(results)} OP_RETURN(s) with size {' and '.join(size_desc)} bytes")
    print("=" * 130)
    print(f"{'Block':>8} {'Date':>20} {'Mined By':<20} {'Size (bytes)':>12} {'Type':<8} {'Fee (sats)':>12} {'Transaction ID':<64}")
    print("-" * 130)
    
    for block_num, block_time, mined_by, txid, size, ftype, tx_fee, fee_rate in results:
        miner = (mined_by or 'Unknown')[:19]
        file_type = (ftype or 'unknown')[:7]
        fee_str = f"{tx_fee:,}" if tx_fee else "N/A"
        print(f"{block_num:>8} {block_time.strftime('%Y-%m-%d %H:%M:%S'):>20} "
              f"{miner:<20} {size:>12,} {file_type:<8} {fee_str:>12} {txid}")
    
    # Show summary stats
    total_size = sum(r[4] for r in results)
    avg_size = total_size / len(results)
    total_fees = sum(r[6] for r in results if r[6])
    
    print("-" * 130)
    print(f"Total: {len(results)} OP_RETURNs, {total_size:,} bytes total, {avg_size:,.0f} bytes average")
    if total_fees:
        print(f"Total fees: {total_fees:,} sats ({total_fees / 100000000:.8f} BTC)")
    
    db.close()

def generate_dashboard(output_file='op_return_dashboard.html'):
    """Generate an interactive HTML dashboard"""
    db = SessionLocal()
    
    print(f"\n[DASHBOARD] Generating dashboard...")
    
    # Get overall statistics
    stats = db.query(
        func.count(OPReturnScan.id).label('total_blocks'),
        func.sum(OPReturnScan.large_op_returns_found).label('total_ops'),
        func.min(OPReturnScan.block_number).label('first_block'),
        func.max(OPReturnScan.block_number).label('last_block')
    ).first()
    
    # Get date range
    first_scan = None
    last_scan = None
    if stats.first_block:
        first_scan = db.query(OPReturnScan).filter(
            OPReturnScan.block_number == stats.first_block
        ).first()
        last_scan = db.query(OPReturnScan).filter(
            OPReturnScan.block_number == stats.last_block
        ).first()
    
    # Get mining pool data
    mining_pools = db.query(
        OPReturnScan.mined_by,
        func.count(OPReturnScan.id).label('block_count'),
        func.sum(OPReturnScan.large_op_returns_found).label('op_count')
    ).group_by(OPReturnScan.mined_by).order_by(desc('op_count')).all()
    
    # Get file type data
    file_types = db.query(
        LargeOPReturn.file_type,
        func.count(LargeOPReturn.id).label('count')
    ).group_by(LargeOPReturn.file_type).order_by(desc('count')).all()
    
    # Get size distribution
    all_sizes = db.query(LargeOPReturn.data_size).all()
    size_ranges = {
        '84-200': (84, 200),
        '200-1K': (201, 1023),
        '1K-10K': (1024, 10239),
        '10K-50K': (10240, 51199),
        '50K-100K': (51200, 102400)
    }
    size_counts = {label: 0 for label in size_ranges.keys()}
    for (size,) in all_sizes:
        for label, (min_size, max_size) in size_ranges.items():
            if min_size <= size <= max_size:
                size_counts[label] += 1
                break
    
    # Get monthly activity data
    scans_with_ops = db.query(OPReturnScan).filter(
        OPReturnScan.large_op_returns_found > 0
    ).order_by(OPReturnScan.block_time).all()
    
    monthly_stats = defaultdict(lambda: {'blocks': 0, 'op_returns': 0, 'file_types': defaultdict(int)})
    for scan in scans_with_ops:
        month_key = scan.block_time.strftime('%Y-%m')
        monthly_stats[month_key]['blocks'] += 1
        monthly_stats[month_key]['op_returns'] += scan.large_op_returns_found
        
        # Get file types for this scan
        for op_return in scan.op_returns:
            ft = op_return.file_type or 'unknown'
            monthly_stats[month_key]['file_types'][ft] += 1
    
    # Get top blocks with most OP_RETURNs
    top_blocks = db.query(OPReturnScan).filter(
        OPReturnScan.large_op_returns_found > 0
    ).order_by(desc(OPReturnScan.large_op_returns_found)).limit(20).all()
    
    db.close()
    
    # Prepare data for JavaScript
    mining_pool_data = {
        'labels': [pool or 'Unknown' for pool, _, _ in mining_pools if _ and _ > 0],
        'block_counts': [int(count) for _, count, ops in mining_pools if ops and ops > 0],
        'op_counts': [int(ops or 0) for _, _, ops in mining_pools if ops and ops > 0]
    }
    
    file_type_data = {
        'labels': [ft or 'unknown' for ft, _ in file_types],
        'counts': [int(count) for _, count in file_types]
    }
    
    size_dist_data = {
        'labels': list(size_counts.keys()),
        'counts': list(size_counts.values())
    }
    
    # Monthly timeline
    sorted_months = sorted(monthly_stats.keys())
    monthly_timeline = {
        'labels': sorted_months,
        'op_counts': [monthly_stats[m]['op_returns'] for m in sorted_months],
        'block_counts': [monthly_stats[m]['blocks'] for m in sorted_months]
    }
    
    # File types over time
    all_file_types = set()
    for month_data in monthly_stats.values():
        all_file_types.update(month_data['file_types'].keys())
    
    file_types_timeline = {
        'labels': sorted_months,
        'datasets': {}
    }
    for ft in sorted(all_file_types):
        file_types_timeline['datasets'][ft] = [
            monthly_stats[m]['file_types'].get(ft, 0) for m in sorted_months
        ]
    
    # Top blocks data
    top_blocks_data = [{
        'block': block.block_number,
        'date': block.block_time.strftime('%Y-%m-%d %H:%M'),
        'miner': block.mined_by or 'Unknown',
        'ops': block.large_op_returns_found
    } for block in top_blocks]
    
    # Generate HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bitcoin OP_RETURN Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            padding: 20px;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        header {{
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }}
        
        h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }}
        
        .subtitle {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.15);
        }}
        
        .stat-label {{
            font-size: 0.9em;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }}
        
        .stat-value {{
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
        }}
        
        .stat-sub {{
            font-size: 0.85em;
            color: #999;
            margin-top: 5px;
        }}
        
        .chart-container {{
            background: white;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        
        .chart-title {{
            font-size: 1.5em;
            font-weight: 600;
            margin-bottom: 20px;
            color: #333;
        }}
        
        .chart-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 30px;
            margin-bottom: 30px;
        }}
        
        .chart-wrapper {{
            position: relative;
            height: 400px;
        }}
        
        .full-width {{
            grid-column: 1 / -1;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
        }}
        
        th {{
            background: #667eea;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
        }}
        
        td {{
            padding: 12px 15px;
            border-bottom: 1px solid #eee;
        }}
        
        tr:hover {{
            background: #f8f9ff;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }}
        
        .badge-danger {{
            background: #fee;
            color: #c00;
        }}
        
        .badge-warning {{
            background: #ffeaa7;
            color: #d63031;
        }}
        
        .badge-info {{
            background: #e3f2fd;
            color: #1976d2;
        }}
        
        footer {{
            text-align: center;
            color: white;
            margin-top: 40px;
            opacity: 0.8;
        }}
        
        @media (max-width: 768px) {{
            .chart-grid {{
                grid-template-columns: 1fr;
            }}
            
            h1 {{
                font-size: 1.8em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⛏️ Bitcoin OP_RETURN Dashboard</h1>
            <p class="subtitle">Large OP_RETURN Data Analytics (>83 bytes)</p>
        </header>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Blocks Scanned</div>
                <div class="stat-value">{stats.total_blocks or 0:,}</div>
                <div class="stat-sub">Blocks analyzed</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Large OP_RETURNs Found</div>
                <div class="stat-value">{stats.total_ops or 0:,}</div>
                <div class="stat-sub">Over 83 bytes</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Block Range</div>
                <div class="stat-value">{stats.first_block or 0:,}</div>
                <div class="stat-sub">to {stats.last_block or 0:,}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Date Range</div>
                <div class="stat-value" style="font-size: 1.2em;">{first_scan.block_time.strftime('%b %Y') if first_scan else 'N/A'}</div>
                <div class="stat-sub">to {last_scan.block_time.strftime('%b %Y') if last_scan else 'N/A'}</div>
            </div>
        </div>
        
        <div class="chart-grid">
            <div class="chart-container">
                <h2 class="chart-title">📊 File Type Distribution</h2>
                <div class="chart-wrapper">
                    <canvas id="fileTypeChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <h2 class="chart-title">📏 Size Distribution</h2>
                <div class="chart-wrapper">
                    <canvas id="sizeChart"></canvas>
                </div>
            </div>
        </div>
        
        <div class="chart-container full-width">
            <h2 class="chart-title">📈 Monthly Activity Timeline</h2>
            <div class="chart-wrapper" style="height: 300px;">
                <canvas id="timelineChart"></canvas>
            </div>
        </div>
        
        <div class="chart-container full-width">
            <h2 class="chart-title">🎨 File Types Over Time</h2>
            <div class="chart-wrapper" style="height: 350px;">
                <canvas id="fileTypesTimelineChart"></canvas>
            </div>
        </div>
        
        <div class="chart-container full-width">
            <h2 class="chart-title">⛏️ Mining Pool Analysis</h2>
            <div class="chart-wrapper" style="height: 400px;">
                <canvas id="miningPoolChart"></canvas>
            </div>
        </div>
        
        <div class="chart-container full-width">
            <h2 class="chart-title">🏆 Top 20 Blocks with Most OP_RETURNs</h2>
            <table>
                <thead>
                    <tr>
                        <th>Block #</th>
                        <th>Date</th>
                        <th>Mined By</th>
                        <th>OP_RETURNs</th>
                    </tr>
                </thead>
                <tbody id="topBlocksTable">
                </tbody>
            </table>
        </div>
        
        <footer>
            <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>Data sourced from Bitcoin blockchain via local Bitcoin Core node</p>
        </footer>
    </div>
    
    <script>
        // Data from Python
        const miningPoolData = {json.dumps(mining_pool_data)};
        const fileTypeData = {json.dumps(file_type_data)};
        const sizeDistData = {json.dumps(size_dist_data)};
        const monthlyTimeline = {json.dumps(monthly_timeline)};
        const fileTypesTimeline = {json.dumps(file_types_timeline)};
        const topBlocksData = {json.dumps(top_blocks_data)};
        
        // Chart.js default settings
        Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        Chart.defaults.plugins.legend.display = true;
        
        // Color palette
        const colors = [
            '#667eea', '#764ba2', '#f093fb', '#4facfe',
            '#43e97b', '#fa709a', '#fee140', '#30cfd0',
            '#a8edea', '#fed6e3', '#89f7fe', '#66a6ff',
            '#f5af19', '#f12711', '#c471f5', '#12c2e9'
        ];
        
        // File Type Pie Chart
        new Chart(document.getElementById('fileTypeChart'), {{
            type: 'doughnut',
            data: {{
                labels: fileTypeData.labels,
                datasets: [{{
                    data: fileTypeData.counts,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        position: 'right',
                        labels: {{
                            padding: 15,
                            font: {{
                                size: 12
                            }}
                        }}
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return label + ': ' + value + ' (' + percentage + '%)';
                            }}
                        }}
                    }}
                }}
            }}
        }});
        
        // Size Distribution Bar Chart
        new Chart(document.getElementById('sizeChart'), {{
            type: 'bar',
            data: {{
                labels: sizeDistData.labels,
                datasets: [{{
                    label: 'Count',
                    data: sizeDistData.counts,
                    backgroundColor: '#667eea',
                    borderColor: '#5568d3',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        ticks: {{
                            precision: 0
                        }}
                    }}
                }}
            }}
        }});
        
        // Monthly Timeline
        new Chart(document.getElementById('timelineChart'), {{
            type: 'line',
            data: {{
                labels: monthlyTimeline.labels,
                datasets: [
                    {{
                        label: 'OP_RETURNs Found',
                        data: monthlyTimeline.op_counts,
                        borderColor: '#667eea',
                        backgroundColor: 'rgba(102, 126, 234, 0.1)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 3
                    }},
                    {{
                        label: 'Blocks with OP_RETURNs',
                        data: monthlyTimeline.block_counts,
                        borderColor: '#764ba2',
                        backgroundColor: 'rgba(118, 75, 162, 0.1)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 3
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false
                }},
                plugins: {{
                    legend: {{
                        position: 'top'
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        ticks: {{
                            precision: 0
                        }}
                    }}
                }}
            }}
        }});
        
        // File Types Over Time (Stacked Area)
        const fileTypeDatasets = Object.keys(fileTypesTimeline.datasets).map((ft, idx) => ({{
            label: ft,
            data: fileTypesTimeline.datasets[ft],
            borderColor: colors[idx % colors.length],
            backgroundColor: colors[idx % colors.length] + '80',
            fill: true,
            tension: 0.4
        }}));
        
        new Chart(document.getElementById('fileTypesTimelineChart'), {{
            type: 'line',
            data: {{
                labels: fileTypesTimeline.labels,
                datasets: fileTypeDatasets
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false
                }},
                plugins: {{
                    legend: {{
                        position: 'top',
                        labels: {{
                            boxWidth: 12,
                            padding: 10
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        stacked: true,
                        beginAtZero: true,
                        ticks: {{
                            precision: 0
                        }}
                    }},
                    x: {{
                        stacked: true
                    }}
                }}
            }}
        }});
        
        // Mining Pool Horizontal Bar Chart
        new Chart(document.getElementById('miningPoolChart'), {{
            type: 'bar',
            data: {{
                labels: miningPoolData.labels,
                datasets: [
                    {{
                        label: 'Blocks Mined',
                        data: miningPoolData.block_counts,
                        backgroundColor: 'rgba(102, 126, 234, 0.3)',
                        borderColor: '#667eea',
                        borderWidth: 1
                    }},
                    {{
                        label: 'OP_RETURNs Found',
                        data: miningPoolData.op_counts,
                        backgroundColor: '#f093fb',
                        borderColor: '#e574ea',
                        borderWidth: 1
                    }}
                ]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        position: 'top'
                    }}
                }},
                scales: {{
                    x: {{
                        beginAtZero: true,
                        ticks: {{
                            precision: 0
                        }}
                    }}
                }}
            }}
        }});
        
        // Populate Top Blocks Table
        const tbody = document.getElementById('topBlocksTable');
        topBlocksData.forEach((block, idx) => {{
            const row = tbody.insertRow();
            
            const badgeClass = block.ops >= 10 ? 'badge-danger' : 
                               block.ops >= 5 ? 'badge-warning' : 'badge-info';
            
            row.innerHTML = `
                <td><strong>${{block.block}}</strong></td>
                <td>${{block.date}}</td>
                <td>${{block.miner}}</td>
                <td><span class="badge ${{badgeClass}}">${{block.ops}} OP_RETURNs</span></td>
            `;
        }});
    </script>
</body>
</html>"""
    
    # Write HTML file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"[SUCCESS] Dashboard generated: {output_file}")
    print(f"[INFO] Open this file in your web browser to view the dashboard")

def generate_timeline(output_file='op_return_timeline.html'):
    """Generate an interactive timeline of text and media OP_RETURNs"""
    db = SessionLocal()
    
    print(f"\n[TIMELINE] Generating interactive timeline...")
    
    # Media types to include (text and visual/audio media)
    media_types = ['text', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'mp4', 'mp3', 'flac', 'ogg', 'avi']
    
    # Query for text and media OP_RETURNs
    results = db.query(
        OPReturnScan.block_number,
        OPReturnScan.block_time,
        OPReturnScan.mined_by,
        LargeOPReturn.txid,
        LargeOPReturn.vout_index,
        LargeOPReturn.data_size,
        LargeOPReturn.file_type,
        LargeOPReturn.mime_type,
        LargeOPReturn.is_text,
        LargeOPReturn.decoded_text,
        LargeOPReturn.tx_fee,
        LargeOPReturn.fee_rate
    ).join(
        LargeOPReturn, OPReturnScan.id == LargeOPReturn.scan_id
    ).filter(
        LargeOPReturn.file_type.in_(media_types)
    ).order_by(
        OPReturnScan.block_time
    ).all()
    
    if not results:
        print("[ERROR] No text or media OP_RETURNs found")
        db.close()
        return
    
    print(f"[INFO] Found {len(results)} text/media OP_RETURNs to include")
    
    # Build data array
    timeline_data = []
    output_dir = Path('op_return_data')
    
    for idx, (block_num, block_time, mined_by, txid, vout_idx, size, ftype, mime, is_text, decoded, fee, fee_rate) in enumerate(results, 1):
        print(f"[INFO] Processing {idx}/{len(results)}: Block {block_num} ({ftype})...", end='\r')
        
        # Find the file on disk
        block_dir = output_dir / f"block_{block_num}"
        base_name = f"tx_{txid}_{vout_idx}"
        
        content = None
        content_type = 'text'
        
        if is_text and decoded:
            # Use decoded text
            content = decoded
            content_type = 'text'
        else:
            # Try to load file from disk
            file_path = None
            
            # Try with extension
            if ftype and ftype != 'binary':
                test_path = block_dir / f"{base_name}.{ftype}"
                if test_path.exists():
                    file_path = test_path
            
            # Fallback to raw.bin
            if not file_path:
                test_path = block_dir / f"{base_name}_raw.bin"
                if test_path.exists():
                    file_path = test_path
            
            if file_path and file_path.exists():
                # Read binary and convert to base64
                with open(file_path, 'rb') as f:
                    binary_data = f.read()
                    content = base64.b64encode(binary_data).decode('utf-8')
                
                # Determine content type
                if ftype in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                    content_type = 'image'
                elif ftype in ['mp4', 'avi']:
                    content_type = 'video'
                elif ftype in ['mp3', 'flac', 'ogg']:
                    content_type = 'audio'
            else:
                print(f"\n[WARNING] File not found for block {block_num}, tx {txid[:16]}...")
                continue
        
        # Create shortened preview for hover
        preview = ''
        if is_text and decoded:
            preview = decoded[:100] + ('...' if len(decoded) > 100 else '')
        
        timeline_data.append({
            'id': f"block_{block_num}_{txid}_{vout_idx}",
            'block': block_num,
            'date': block_time.strftime('%Y-%m-%d %H:%M:%S'),
            'timestamp': int(block_time.timestamp()),
            'miner': mined_by or 'Unknown',
            'txid': txid,
            'vout': vout_idx,
            'size': size,
            'type': ftype or 'text',
            'mime': mime or 'text/plain',
            'contentType': content_type,
            'content': content,
            'preview': preview,
            'fee': fee if fee else 0,
            'feeRate': round(fee_rate, 2) if fee_rate else 0
        })
    
    print(f"\n[INFO] Successfully loaded {len(timeline_data)} items")
    
    db.close()
    
    # Generate HTML with embedded data and JavaScript
    html_content = generate_timeline_html(timeline_data)
    
    # Write HTML file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"[SUCCESS] Timeline generated: {output_file}")
    print(f"[INFO] {len(timeline_data)} items included in timeline")
    print(f"[INFO] Open this file in your web browser to view the interactive timeline")

def generate_timeline_html(timeline_data):
    """Generate the HTML content for the timeline"""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bitcoin OP_RETURN Timeline</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0e27;
            color: #e0e0e0;
            overflow-x: hidden;
        }}
        
        .header {{
            padding: 20px;
            background: linear-gradient(135deg, #1a1f3a 0%, #0a0e27 100%);
            border-bottom: 2px solid #00ffff;
            box-shadow: 0 4px 20px rgba(0, 255, 255, 0.3);
        }}
        
        h1 {{
            font-size: 2.5em;
            text-align: center;
            background: linear-gradient(90deg, #00ffff, #ff00ff, #ffff00);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 10px;
            text-shadow: 0 0 30px rgba(0, 255, 255, 0.5);
        }}
        
        .subtitle {{
            text-align: center;
            color: #888;
            font-size: 0.9em;
        }}
        
        .controls {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background: #1a1f3a;
            border-bottom: 1px solid #333;
            flex-wrap: wrap;
            gap: 15px;
        }}
        
        .control-group {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        
        .control-group label {{
            color: #aaa;
            font-size: 0.9em;
        }}
        
        input[type="text"], input[type="number"] {{
            background: #0a0e27;
            border: 1px solid #444;
            color: #fff;
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 0.9em;
        }}
        
        input[type="text"]:focus, input[type="number"]:focus {{
            outline: none;
            border-color: #00ffff;
            box-shadow: 0 0 10px rgba(0, 255, 255, 0.3);
        }}
        
        button {{
            background: linear-gradient(135deg, #00ffff 0%, #0088ff 100%);
            border: none;
            color: #000;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            font-size: 0.9em;
            transition: all 0.3s;
        }}
        
        button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(0, 255, 255, 0.5);
        }}
        
        .filter-chips {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        
        .chip {{
            padding: 6px 12px;
            border-radius: 20px;
            border: 2px solid;
            cursor: pointer;
            font-size: 0.85em;
            transition: all 0.3s;
            background: #1a1f3a;
            opacity: 0.3;
            filter: grayscale(80%);
        }}
        
        .chip.active {{
            background: rgba(255, 255, 255, 0.15);
            box-shadow: 0 0 15px;
            opacity: 1;
            font-weight: bold;
            filter: grayscale(0%);
        }}
        
        .chip:hover {{
            transform: translateY(-2px);
            opacity: 0.8;
            filter: grayscale(40%);
        }}
        
        .stats-bar {{
            padding: 10px 20px;
            background: #0f1428;
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-around;
            font-size: 0.9em;
        }}
        
        .stat-item {{
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 1.5em;
            font-weight: bold;
            background: linear-gradient(90deg, #00ffff, #ff00ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .stat-label {{
            color: #888;
            font-size: 0.85em;
        }}
        
        .timeline-container {{
            position: relative;
            padding: 100px 50px;
            overflow-x: auto;
            overflow-y: visible;
            min-height: 600px;
            max-width: 100%;
            background: #0a0e27;
        }}
        
        .timeline-container::-webkit-scrollbar {{
            height: 12px;
        }}
        
        .timeline-container::-webkit-scrollbar-track {{
            background: #1a1f3a;
            border-radius: 6px;
        }}
        
        .timeline-container::-webkit-scrollbar-thumb {{
            background: linear-gradient(135deg, #00ffff 0%, #0088ff 100%);
            border-radius: 6px;
        }}
        
        .timeline-container::-webkit-scrollbar-thumb:hover {{
            background: linear-gradient(135deg, #00ffff 0%, #ff00ff 100%);
        }}
        
        .timeline-svg {{
            width: 100%;
            min-height: 600px;
        }}
        
        .timeline-axis {{
            stroke: #444;
            stroke-width: 2;
        }}
        
        .node-group {{
            cursor: pointer;
            transition: all 0.3s;
        }}
        
        .node-circle {{
            transition: all 0.3s;
        }}
        
        .node-group:hover .node-circle {{
            filter: brightness(1.5);
        }}
        
        .node-group:hover .node-line {{
            stroke-width: 3;
            filter: brightness(1.5);
        }}
        
        .node-group:hover .node-label {{
            opacity: 1;
        }}
        
        .node-line {{
            stroke-width: 2;
            transition: all 0.3s;
        }}
        
        .node-label {{
            font-size: 12px;
            fill: #fff;
            opacity: 0.7;
            transition: opacity 0.3s;
            pointer-events: none;
        }}
        
        .date-label {{
            font-size: 11px;
            fill: #888;
        }}
        
        /* Color scheme for file types */
        .type-text {{ stroke: #00ffff; fill: #00ffff; }}
        .type-jpg, .type-jpeg, .type-png, .type-gif, .type-webp, .type-bmp {{ stroke: #ff00ff; fill: #ff00ff; }}
        .type-mp4, .type-avi {{ stroke: #ffff00; fill: #ffff00; }}
        .type-mp3, .type-flac, .type-ogg {{ stroke: #00ff00; fill: #00ff00; }}
        
        /* Modal */
        .modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.9);
            z-index: 1000;
            overflow-y: auto;
        }}
        
        .modal.active {{
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        
        .modal-content {{
            background: #1a1f3a;
            border: 2px solid #00ffff;
            border-radius: 10px;
            padding: 30px;
            max-width: 90%;
            max-height: 90%;
            overflow-y: auto;
            box-shadow: 0 0 50px rgba(0, 255, 255, 0.5);
            position: relative;
        }}
        
        .modal-close {{
            position: absolute;
            top: 15px;
            right: 15px;
            font-size: 2em;
            cursor: pointer;
            color: #00ffff;
            background: none;
            border: none;
            padding: 0;
            width: 40px;
            height: 40px;
            line-height: 1;
        }}
        
        .modal-close:hover {{
            color: #ff00ff;
            transform: rotate(90deg);
        }}
        
        .modal-header {{
            border-bottom: 2px solid #00ffff;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}
        
        .modal-title {{
            font-size: 1.5em;
            color: #00ffff;
        }}
        
        .modal-meta {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
            padding: 15px;
            background: #0a0e27;
            border-radius: 5px;
        }}
        
        .meta-item {{
            display: flex;
            flex-direction: column;
        }}
        
        .meta-label {{
            color: #888;
            font-size: 0.85em;
            margin-bottom: 5px;
        }}
        
        .meta-value {{
            color: #fff;
            font-weight: bold;
        }}
        
        .modal-preview {{
            margin-top: 20px;
            padding: 20px;
            background: #0a0e27;
            border-radius: 5px;
            border: 1px solid #333;
        }}
        
        .modal-preview img, .modal-preview video, .modal-preview audio {{
            max-width: 100%;
            border-radius: 5px;
            border: 1px solid #444;
        }}
        
        .modal-preview pre {{
            white-space: pre-wrap;
            word-wrap: break-word;
            color: #00ffff;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            line-height: 1.5;
            max-height: 400px;
            overflow-y: auto;
        }}
        
        .tooltip {{
            position: absolute;
            background: rgba(0, 0, 0, 0.95);
            border: 1px solid #00ffff;
            padding: 10px;
            border-radius: 5px;
            pointer-events: none;
            z-index: 999;
            max-width: 300px;
            font-size: 0.85em;
            display: none;
        }}
        
        .tooltip.active {{
            display: block;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>⛏️ Bitcoin OP_RETURN Timeline</h1>
        <p class="subtitle">Interactive Timeline of Text and Media Data Stored on Bitcoin Blockchain</p>
    </div>
    
    <div class="controls">
        <div class="control-group">
            <label>Search Block:</label>
            <input type="number" id="searchBlock" placeholder="Block number">
            <button onclick="jumpToBlock()">Jump</button>
        </div>
        
        <div class="control-group">
            <label>Filter:</label>
            <div class="filter-chips" id="filterChips"></div>
        </div>
        
        <div class="control-group">
            <label>Zoom:</label>
            <button onclick="adjustZoom(0.8)">-</button>
            <button onclick="adjustZoom(1.25)">+</button>
            <button onclick="resetView()">Reset</button>
        </div>
        
        <div class="control-group">
            <button id="spacingToggle" onclick="toggleSpacing()">Even Spacing</button>
        </div>
    </div>
    
    <div class="stats-bar" id="statsBar"></div>
    
    <div class="timeline-container" id="timelineContainer">
        <svg class="timeline-svg" id="timelineSvg"></svg>
    </div>
    
    <div class="modal" id="modal">
        <div class="modal-content">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <div class="modal-header">
                <div class="modal-title" id="modalTitle"></div>
            </div>
            <div class="modal-meta" id="modalMeta"></div>
            <div class="modal-preview" id="modalPreview"></div>
        </div>
    </div>
    
    <div class="tooltip" id="tooltip"></div>
    
    <script>
        // Timeline data embedded at end of file
        const TIMELINE_DATA = {json.dumps(timeline_data, indent=2)};
        
        // State
        let currentZoom = 1;
        let activeFilters = new Set();
        let filteredData = [...TIMELINE_DATA];
        let forceEvenSpacing = false;
        
        // Color mapping
        const colorMap = {{
            'text': '#00ffff',
            'jpg': '#ff00ff', 'jpeg': '#ff00ff', 'png': '#ff00ff', 
            'gif': '#ff00ff', 'webp': '#ff00ff', 'bmp': '#ff00ff',
            'mp4': '#ffff00', 'avi': '#ffff00',
            'mp3': '#00ff00', 'flac': '#00ff00', 'ogg': '#00ff00'
        }};
        
        // Initialize
        function init() {{
            setupFilters();
            updateSpacingButton();
            updateStats();
            renderTimeline();
            checkHash();
        }}
        
        // Setup filter chips
        function setupFilters() {{
            const types = [...new Set(TIMELINE_DATA.map(d => d.type))];
            const chipsContainer = document.getElementById('filterChips');
            
            types.forEach(type => {{
                const chip = document.createElement('div');
                chip.className = `chip type-${{type}} active`;
                chip.textContent = type.toUpperCase();
                chip.style.borderColor = colorMap[type] || '#fff';
                chip.style.boxShadow = `0 0 10px ${{colorMap[type] || '#fff'}}`;
                chip.onclick = () => toggleFilter(type, chip);
                chipsContainer.appendChild(chip);
                activeFilters.add(type);
            }});
        }}
        
        // Toggle filter
        function toggleFilter(type, chipEl) {{
            if (activeFilters.has(type)) {{
                activeFilters.delete(type);
                chipEl.classList.remove('active');
            }} else {{
                activeFilters.add(type);
                chipEl.classList.add('active');
            }}
            applyFilters();
        }}
        
        // Apply filters
        function applyFilters() {{
            filteredData = TIMELINE_DATA.filter(d => activeFilters.has(d.type));
            updateStats();
            renderTimeline();
        }}
        
        // Update stats
        function updateStats() {{
            const statsBar = document.getElementById('statsBar');
            const totalSize = filteredData.reduce((sum, d) => sum + d.size, 0);
            const totalFees = filteredData.reduce((sum, d) => sum + d.fee, 0);
            const typeCounts = {{}};
            
            filteredData.forEach(d => {{
                typeCounts[d.type] = (typeCounts[d.type] || 0) + 1;
            }});
            
            const typeBreakdown = Object.entries(typeCounts)
                .map(([type, count]) => `${{type}}: ${{count}}`)
                .join(', ');
            
            statsBar.innerHTML = `
                <div class="stat-item">
                    <div class="stat-value">${{filteredData.length}}</div>
                    <div class="stat-label">OP_RETURNs</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${{(totalSize / 1024 / 1024).toFixed(2)}} MB</div>
                    <div class="stat-label">Total Data</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${{(totalFees / 100000000).toFixed(4)}} BTC</div>
                    <div class="stat-label">Total Fees</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${{typeBreakdown}}</div>
                    <div class="stat-label">Type Breakdown</div>
                </div>
            `;
        }}
        
        // Render timeline
        function renderTimeline() {{
            if (filteredData.length === 0) {{
                document.getElementById('timelineSvg').innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#888">No data to display</text>';
                return;
            }}
            
            const container = document.getElementById('timelineContainer');
            const svg = document.getElementById('timelineSvg');
            
            const margin = {{ top: 100, right: 50, bottom: 100, left: 50 }};
            // Ensure minimum 60px per node to avoid clustering
            const minWidth = filteredData.length * 60 * currentZoom;
            const width = Math.max(container.clientWidth, minWidth, 2000);
            const height = 600;
            
            svg.setAttribute('width', width);
            svg.setAttribute('height', height);
            
            // Calculate positions - ensure minimum spacing
            const timelineY = height / 2;
            const availableWidth = width - margin.left - margin.right;
            const minSpacing = 60 * currentZoom;  // Minimum 60px between nodes
            const useIndexSpacing = forceEvenSpacing || (filteredData.length * minSpacing) > availableWidth * 0.7;
            
            // Set minTime to the 1st of the month for the first block
            const firstBlockDate = new Date(filteredData[0].timestamp * 1000);
            const minTimeDate = new Date(firstBlockDate.getFullYear(), firstBlockDate.getMonth(), 1, 0, 0, 0);
            const minTime = Math.floor(minTimeDate.getTime() / 1000);
            
            const maxTime = filteredData[filteredData.length - 1].timestamp;
            const timeRange = maxTime - minTime || 1;
            
            // Clear existing content
            svg.innerHTML = '';
            
            // Draw timeline axis
            const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            line.setAttribute('class', 'timeline-axis');
            line.setAttribute('x1', margin.left);
            line.setAttribute('y1', timelineY);
            line.setAttribute('x2', width - margin.right);
            line.setAttribute('y2', timelineY);
            svg.appendChild(line);
            
            // Draw nodes
            filteredData.forEach((item, idx) => {{
                // Use hybrid positioning: time-based but with minimum spacing enforcement
                let x;
                if (useIndexSpacing) {{
                    // Use index-based spacing when nodes would be too clustered
                    x = margin.left + (idx / (filteredData.length - 1 || 1)) * availableWidth;
                }} else {{
                    // Use time-based positioning when there's enough space
                    x = margin.left + ((item.timestamp - minTime) / timeRange) * availableWidth;
                }}
                
                const yOffset = (idx % 2 === 0) ? -150 : 150;
                const nodeY = timelineY + yOffset;
                
                // Create group
                const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
                g.setAttribute('class', 'node-group');
                g.setAttribute('data-id', item.id);
                g.style.cursor = 'pointer';
                
                // Connection line
                const connLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                connLine.setAttribute('class', `node-line type-${{item.type}}`);
                connLine.setAttribute('x1', x);
                connLine.setAttribute('y1', timelineY);
                connLine.setAttribute('x2', x);
                connLine.setAttribute('y2', nodeY);
                connLine.setAttribute('stroke', colorMap[item.type] || '#fff');
                connLine.style.filter = `drop-shadow(0 0 5px ${{colorMap[item.type] || '#fff'}})`;
                g.appendChild(connLine);
                
                // Node circle
                const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                circle.setAttribute('class', `node-circle type-${{item.type}}`);
                circle.setAttribute('cx', x);
                circle.setAttribute('cy', nodeY);
                circle.setAttribute('r', 8);
                circle.setAttribute('fill', 'none');
                circle.setAttribute('stroke', colorMap[item.type] || '#fff');
                circle.setAttribute('stroke-width', 3);
                circle.style.filter = `drop-shadow(0 0 8px ${{colorMap[item.type] || '#fff'}})`;
                g.appendChild(circle);
                
                // Label
                const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                label.setAttribute('class', `node-label type-${{item.type}}`);
                label.setAttribute('x', x);
                label.setAttribute('y', nodeY + (yOffset > 0 ? 25 : -15));
                label.setAttribute('text-anchor', 'middle');
                label.textContent = `Block ${{item.block}}`;
                g.appendChild(label);
                
                const label2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                label2.setAttribute('class', `node-label type-${{item.type}}`);
                label2.setAttribute('x', x);
                label2.setAttribute('y', nodeY + (yOffset > 0 ? 40 : -30));
                label2.setAttribute('text-anchor', 'middle');
                label2.textContent = `${{(item.size / 1024).toFixed(1)}}KB ${{item.type}}`;
                g.appendChild(label2);
                
                // Events
                g.addEventListener('click', () => openModal(item));
                g.addEventListener('mouseenter', (e) => showTooltip(e, item));
                g.addEventListener('mouseleave', hideTooltip);
                
                svg.appendChild(g);
            }});
            
            // Add monthly tick marks (1st of each month)
            const firstDate = new Date(filteredData[0].timestamp * 1000);
            const lastDate = new Date(filteredData[filteredData.length - 1].timestamp * 1000);
            
            // Generate array of first-of-month dates
            const monthlyMarkers = [];
            const current = new Date(firstDate.getFullYear(), firstDate.getMonth(), 1);
            
            while (current <= lastDate) {{
                monthlyMarkers.push({{
                    date: new Date(current),
                    timestamp: Math.floor(current.getTime() / 1000),
                    label: current.toLocaleDateString('en-US', {{ month: 'short', year: 'numeric' }})
                }});
                current.setMonth(current.getMonth() + 1);
            }}
            
            // Draw monthly tick marks
            monthlyMarkers.forEach(marker => {{
                // Calculate x position
                let x;
                if (useIndexSpacing) {{
                    // Find closest node to this date
                    let closestIdx = 0;
                    let minDiff = Math.abs(filteredData[0].timestamp - marker.timestamp);
                    
                    filteredData.forEach((item, idx) => {{
                        const diff = Math.abs(item.timestamp - marker.timestamp);
                        if (diff < minDiff) {{
                            minDiff = diff;
                            closestIdx = idx;
                        }}
                    }});
                    
                    x = margin.left + (closestIdx / (filteredData.length - 1 || 1)) * availableWidth;
                }} else {{
                    // Use timestamp-based positioning
                    x = margin.left + ((marker.timestamp - minTime) / timeRange) * availableWidth;
                }}
                
                // Only draw if within bounds
                if (x >= margin.left && x <= width - margin.right) {{
                    // Tick mark line
                    const tick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                    tick.setAttribute('x1', x);
                    tick.setAttribute('y1', timelineY - 10);
                    tick.setAttribute('x2', x);
                    tick.setAttribute('y2', timelineY + 10);
                    tick.setAttribute('stroke', '#666');
                    tick.setAttribute('stroke-width', 2);
                    svg.appendChild(tick);
                    
                    // Month label
                    const dateLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    dateLabel.setAttribute('class', 'date-label');
                    dateLabel.setAttribute('x', x);
                    dateLabel.setAttribute('y', timelineY + 30);
                    dateLabel.setAttribute('text-anchor', 'middle');
                    dateLabel.textContent = marker.label;
                    svg.appendChild(dateLabel);
                }}
            }});
        }}
        
        // Show tooltip
        function showTooltip(e, item) {{
            const tooltip = document.getElementById('tooltip');
            tooltip.innerHTML = `
                <strong>Block ${{item.block}}</strong><br>
                Date: ${{item.date}}<br>
                Size: ${{item.size.toLocaleString()}} bytes<br>
                Type: ${{item.type}}<br>
                Miner: ${{item.miner}}<br>
                ${{item.preview ? `<br><em>${{item.preview}}</em>` : ''}}
            `;
            tooltip.style.left = (e.pageX + 10) + 'px';
            tooltip.style.top = (e.pageY + 10) + 'px';
            tooltip.classList.add('active');
        }}
        
        // Hide tooltip
        function hideTooltip() {{
            document.getElementById('tooltip').classList.remove('active');
        }}
        
        // Open modal
        function openModal(item) {{
            const modal = document.getElementById('modal');
            const title = document.getElementById('modalTitle');
            const meta = document.getElementById('modalMeta');
            const preview = document.getElementById('modalPreview');
            
            title.textContent = `Block ${{item.block}} - ${{item.type.toUpperCase()}} (${{(item.size / 1024).toFixed(2)}} KB)`;
            
            meta.innerHTML = `
                <div class="meta-item">
                    <div class="meta-label">Block Number</div>
                    <div class="meta-value">${{item.block}}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Date</div>
                    <div class="meta-value">${{item.date}}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Miner</div>
                    <div class="meta-value">${{item.miner}}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Transaction ID</div>
                    <div class="meta-value" style="font-size: 0.8em; word-break: break-all;">${{item.txid}}</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Data Size</div>
                    <div class="meta-value">${{item.size.toLocaleString()}} bytes</div>
                </div>
                <div class="meta-item">
                    <div class="meta-label">Fee</div>
                    <div class="meta-value">${{item.fee.toLocaleString()}} sats (${{item.feeRate}} sat/vB)</div>
                </div>
            `;
            
            // Render content based on type
            if (item.contentType === 'text') {{
                preview.innerHTML = `<pre>${{escapeHtml(item.content)}}</pre>`;
            }} else if (item.contentType === 'image') {{
                preview.innerHTML = `<img src="data:${{item.mime}};base64,${{item.content}}" alt="OP_RETURN Image">`;
            }} else if (item.contentType === 'video') {{
                preview.innerHTML = `<video controls><source src="data:${{item.mime}};base64,${{item.content}}" type="${{item.mime}}"></video>`;
            }} else if (item.contentType === 'audio') {{
                preview.innerHTML = `<audio controls><source src="data:${{item.mime}};base64,${{item.content}}" type="${{item.mime}}"></audio>`;
            }}
            
            modal.classList.add('active');
            window.location.hash = item.id;
        }}
        
        // Close modal
        function closeModal() {{
            document.getElementById('modal').classList.remove('active');
            history.pushState("", document.title, window.location.pathname);
        }}
        
        // Escape HTML
        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}
        
        // Jump to block
        function jumpToBlock() {{
            const blockNum = parseInt(document.getElementById('searchBlock').value);
            const item = TIMELINE_DATA.find(d => d.block === blockNum);
            if (item) {{
                openModal(item);
                // Scroll to node
                const node = document.querySelector(`[data-id="${{item.id}}"]`);
                if (node) {{
                    node.scrollIntoView({{ behavior: 'smooth', block: 'center', inline: 'center' }});
                }}
            }} else {{
                alert('Block not found in timeline');
            }}
        }}
        
        // Zoom
        function adjustZoom(factor) {{
            currentZoom *= factor;
            currentZoom = Math.max(0.5, Math.min(5, currentZoom));
            renderTimeline();
        }}
        
        // Reset view
        function resetView() {{
            currentZoom = 1;
            forceEvenSpacing = false;
            activeFilters = new Set(TIMELINE_DATA.map(d => d.type));
            document.querySelectorAll('.chip').forEach(chip => chip.classList.add('active'));
            updateSpacingButton();
            applyFilters();
        }}
        
        // Toggle spacing mode
        function toggleSpacing() {{
            forceEvenSpacing = !forceEvenSpacing;
            updateSpacingButton();
            renderTimeline();
        }}
        
        // Update spacing button appearance
        function updateSpacingButton() {{
            const btn = document.getElementById('spacingToggle');
            if (forceEvenSpacing) {{
                btn.textContent = 'Time-Based';
                btn.style.background = 'linear-gradient(135deg, #ff00ff 0%, #ff0088 100%)';
            }} else {{
                btn.textContent = 'Even Spacing';
                btn.style.background = 'linear-gradient(135deg, #00ffff 0%, #0088ff 100%)';
            }}
        }}
        
        // Check URL hash
        function checkHash() {{
            const hash = window.location.hash.substring(1);
            if (hash) {{
                const item = TIMELINE_DATA.find(d => d.id === hash);
                if (item) {{
                    setTimeout(() => openModal(item), 500);
                }}
            }}
        }}
        
        // Handle window resize
        window.addEventListener('resize', () => {{
            renderTimeline();
        }});
        
        // Close modal with ESC key
        window.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') {{
                closeModal();
            }}
        }});
        
        // Initialize on load
        window.addEventListener('load', init);
    </script>
</body>
</html>'''

def main():
    parser = argparse.ArgumentParser(description='Query OP_RETURN data from database')
    parser.add_argument('--stats', '-s', action='store_true', help='Show statistics')
    parser.add_argument('--list', '-l', type=int, metavar='N', help='List last N blocks')
    parser.add_argument('--block', '-b', type=int, help='Show details for specific block')
    parser.add_argument('--txid', '-t', help='Search by transaction ID')
    parser.add_argument('--filetype', '-f', help='Search by file type (e.g., jpg, text, binary)')
    parser.add_argument('--min', type=int, metavar='BYTES', help='Minimum OP_RETURN size in bytes')
    parser.add_argument('--max', type=int, metavar='BYTES', help='Maximum OP_RETURN size in bytes')
    parser.add_argument('--generate_dashboard', '-d', metavar='FILE', nargs='?', 
                       const='op_return_dashboard.html', 
                       help='Generate HTML dashboard (default: op_return_dashboard.html)')
    parser.add_argument('--generate_timeline', '-tl', metavar='FILE', nargs='?',
                       const='op_return_timeline.html',
                       help='Generate interactive timeline of text/media OP_RETURNs (default: op_return_timeline.html)')
    
    args = parser.parse_args()
    
    if args.generate_dashboard:
        generate_dashboard(args.generate_dashboard)
    elif args.generate_timeline:
        generate_timeline(args.generate_timeline)
    elif args.stats:
        show_statistics()
    elif args.list:
        list_blocks(args.list)
    elif args.block:
        show_block_details(args.block)
    elif args.txid:
        search_by_txid(args.txid)
    elif args.filetype:
        search_by_file_type(args.filetype)
    elif args.min is not None or args.max is not None:
        search_by_size_range(args.min, args.max)
    else:
        # Default: show statistics
        show_statistics()
        print()
        list_blocks(10)

if __name__ == "__main__":
    main()

