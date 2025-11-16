#!/usr/bin/env python3
"""
Generate timeline data from op_return_data directory
Scans all block directories and extracts metadata for timeline visualization
"""

import json
import os
from pathlib import Path
from datetime import datetime

def is_interesting_text(content, file_type):
    """
    Determine if text content is interesting (human messages) vs technical/boring
    
    Filters out:
    - JSON data
    - Binary/hex dumps
    - Code-like content
    - Very short messages (< 20 chars)
    - Encoded/encrypted looking data
    """
    if not content or file_type != 'text':
        return False
    
    # Too short to be interesting
    if len(content) < 20:
        return False
    
    # Looks like JSON (contains lots of braces and brackets together with colons)
    # Note: Biblical text has colons for verses, so check for braces/brackets primarily
    json_indicators = content.count('{') + content.count('[') + (content.count('"') // 10)
    if json_indicators > 5:
        return False
    
    # Check for high ratio of special characters (likely encoded/binary)
    special_chars = sum(1 for c in content if not c.isalnum() and not c.isspace() and c not in '.,!?;:\'"()-')
    if len(content) > 0 and (special_chars / len(content)) > 0.3:
        return False
    
    # Check for repetitive patterns (likely technical data)
    if content.count('.') > len(content) / 10:  # Too many dots
        return False
    
    # Looks like hex or base64
    hex_like = sum(1 for c in content if c in '0123456789abcdefABCDEF')
    if len(content) > 0 and (hex_like / len(content)) > 0.7:
        return False
    
    # Check for readable words (has vowels, normal word patterns)
    vowels = sum(1 for c in content.lower() if c in 'aeiou')
    if len(content) > 0 and (vowels / len(content)) < 0.1:  # Too few vowels
        return False
    
    # Passed all filters - looks like interesting human text!
    return True

def scan_op_return_data(data_dir='op_return_data'):
    """Scan op_return_data directory and extract timeline data from metadata files"""
    
    timeline_data = []
    data_path = Path(data_dir)
    
    if not data_path.exists():
        print(f"Error: {data_dir} directory not found")
        return []
    
    # Get all block directories
    block_dirs = sorted([d for d in data_path.iterdir() if d.is_dir() and d.name.startswith('block_')])
    
    print(f"Scanning {len(block_dirs)} block directories...")
    
    for block_dir in block_dirs:
        # Find all metadata JSON files
        metadata_files = list(block_dir.glob('*_metadata.json'))
        
        for metadata_file in metadata_files:
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                # Extract relevant data
                block_num = metadata.get('block_number')
                block_time = metadata.get('block_time')
                txid = metadata.get('transaction_id')
                vout = metadata.get('vout_index')
                size = metadata.get('data_size', 0)
                file_type = metadata.get('file_type', 'unknown')
                mime_type = metadata.get('mime_type', '')
                miner = metadata.get('mined_by', 'Unknown')
                
                # Fee information
                fee = metadata.get('transaction_fee_sats')
                fee_rate = metadata.get('fee_rate_sats_per_vbyte')
                
                # Parse timestamp
                if block_time:
                    try:
                        dt = datetime.fromisoformat(block_time.replace('Z', '+00:00'))
                        timestamp = int(dt.timestamp())
                    except:
                        timestamp = None
                else:
                    timestamp = None
                
                # Create unique ID
                item_id = f"block_{block_num}_{txid}_{vout}"
                
                # Check if we have the actual file for preview
                file_path = block_dir / f"tx_{txid}_{vout}.{file_type}"
                decoded_path = block_dir / f"tx_{txid}_{vout}_decoded.txt"
                
                has_file = file_path.exists()
                has_decoded = decoded_path.exists()
                
                # Read preview text if available
                preview = None
                full_content = None
                if has_decoded and file_type == 'text':
                    try:
                        with open(decoded_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            full_content = content
                            preview = content[:200] + ('...' if len(content) > 200 else '')
                    except:
                        pass
                
                # Filter: Only include media types and interesting text
                media_types = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg',  # Images
                              'mp4', 'avi', 'webm', 'mov',  # Video
                              'mp3', 'flac', 'ogg', 'wav'}  # Audio
                
                # Skip if not media and not interesting text
                if file_type not in media_types:
                    if file_type != 'text' or not is_interesting_text(full_content, file_type):
                        continue  # Skip this item
                
                # Build timeline item
                item = {
                    'id': item_id,
                    'block': block_num,
                    'timestamp': timestamp,
                    'date': block_time,
                    'txid': txid,
                    'vout': vout,
                    'size': size,
                    'type': file_type,
                    'mime': mime_type,
                    'miner': miner,
                    'fee': fee,
                    'feeRate': fee_rate,
                    'hasFile': has_file,
                    'hasDecoded': has_decoded,
                    'preview': preview,
                    'blockDir': block_dir.name
                }
                
                timeline_data.append(item)
                
            except Exception as e:
                print(f"Error processing {metadata_file}: {e}")
                continue
    
    # Sort by timestamp
    timeline_data.sort(key=lambda x: x['timestamp'] if x['timestamp'] else 0)
    
    print(f"Found {len(timeline_data)} OP_RETURN items")
    
    return timeline_data

def main():
    """Main function"""
    print("Generating timeline data from op_return_data directory...\n")
    
    timeline_data = scan_op_return_data()
    
    if timeline_data:
        # Save to JSON file inside op_return_data directory
        output_file = Path('op_return_data') / 'timeline_data.json'
        with open(output_file, 'w') as f:
            json.dump(timeline_data, f, indent=2)
        
        print(f"\n[SUCCESS] Successfully generated {output_file}")
        print(f"   Total items: {len(timeline_data)}")
        
        # Show some stats
        types = {}
        for item in timeline_data:
            t = item['type']
            types[t] = types.get(t, 0) + 1
        
        print("\n[STATS] File type breakdown:")
        for file_type, count in sorted(types.items(), key=lambda x: -x[1]):
            print(f"   {file_type}: {count}")
        
        # Date range
        if timeline_data:
            first_date = timeline_data[0]['date']
            last_date = timeline_data[-1]['date']
            print(f"\n[DATE RANGE]")
            print(f"   First: {first_date}")
            print(f"   Last:  {last_date}")
    else:
        print("[ERROR] No data found")

if __name__ == '__main__':
    main()

