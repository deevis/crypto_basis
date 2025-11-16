import os
import json
import logging
import subprocess
from datetime import datetime
from dotenv import load_dotenv
from btc_service import BTCService
from pathlib import Path
import binascii
from db_config import SessionLocal, init_db
from models import OPReturnScan, LargeOPReturn
from sqlalchemy import func

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class OPReturnScanner:
    def __init__(self, output_dir="bitcoin_large_op_returns/op_return_data", use_database=True, auto_sync_git=None):
        # Load environment variables
        load_dotenv()
        
        self.btc_service = BTCService(test_connection=True)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.use_database = use_database
        
        # Auto-sync git: check environment variable if not explicitly set
        if auto_sync_git is None:
            auto_sync_git = os.getenv('OP_RETURN_AUTO_SYNC_GIT', 'false').lower() in ('true', '1', 'yes')
        self.auto_sync_git = auto_sync_git
        
        # Get GitHub token for authentication
        self.github_token = os.getenv('GITHUB_TOKEN')
        
        # Determine submodule root (parent of op_return_data directory)
        # If output_dir is bitcoin_large_op_returns/op_return_data, submodule_root is bitcoin_large_op_returns
        if 'op_return_data' in str(self.output_dir):
            self.submodule_root = self.output_dir.parent
        else:
            # If output_dir is just bitcoin_large_op_returns, use it directly
            self.submodule_root = self.output_dir if 'bitcoin_large_op_returns' in str(self.output_dir) else None
        
        if self.use_database:
            # Initialize database tables
            init_db()
            self.db = SessionLocal()
        
        # File signatures for detection (magic numbers)
        # Order matters - more specific signatures should come first
        self.file_signatures = {
            # Images
            b'\xFF\xD8\xFF': ('jpg', 'image/jpeg'),
            b'\x89PNG\r\n\x1a\n': ('png', 'image/png'),
            b'GIF87a': ('gif', 'image/gif'),
            b'GIF89a': ('gif', 'image/gif'),
            b'RIFF': ('webp', 'image/webp'),  # Also used by AVI, but less common in blockchain
            b'BM': ('bmp', 'image/bmp'),
            b'\x49\x49\x2A\x00': ('tiff', 'image/tiff'),  # Little-endian TIFF
            b'\x4D\x4D\x00\x2A': ('tiff', 'image/tiff'),  # Big-endian TIFF
            b'\x00\x00\x01\x00': ('ico', 'image/x-icon'),
            
            # Documents
            b'%PDF': ('pdf', 'application/pdf'),
            b'\xD0\xCF\x11\xE0': ('doc', 'application/msword'),  # Old DOC format
            b'PK\x03\x04': ('zip', 'application/zip'),  # Could also be DOCX/XLSX/JAR/APK
            
            # Archives
            b'\x37\x7A\xBC\xAF\x27\x1C': ('7z', 'application/x-7z-compressed'),
            b'Rar!\x1A\x07\x00': ('rar', 'application/x-rar-compressed'),  # RAR 1.5+
            b'Rar!\x1A\x07\x01\x00': ('rar', 'application/x-rar-compressed'),  # RAR 5.0+
            b'\x1F\x8B': ('gz', 'application/gzip'),
            b'BZh': ('bz2', 'application/x-bzip2'),
            b'\x75\x73\x74\x61\x72': ('tar', 'application/x-tar'),  # At offset 257, but checking here
            
            # Audio
            b'ID3': ('mp3', 'audio/mpeg'),
            b'\xFF\xFB': ('mp3', 'audio/mpeg'),  # MP3 without ID3
            b'\xFF\xF3': ('mp3', 'audio/mpeg'),  # MP3 without ID3
            b'fLaC': ('flac', 'audio/flac'),
            b'OggS': ('ogg', 'audio/ogg'),
            
            # Video
            b'\x00\x00\x00\x18ftypmp42': ('mp4', 'video/mp4'),
            b'\x00\x00\x00\x20ftypmp42': ('mp4', 'video/mp4'),
            b'\x00\x00\x00\x18ftypisom': ('mp4', 'video/mp4'),
            b'\x00\x00\x00\x20ftypisom': ('mp4', 'video/mp4'),
            b'RIFF': ('avi', 'video/x-msvideo'),  # Must check for AVI list later
            
            # Executables
            b'MZ': ('exe', 'application/x-msdownload'),  # Windows PE
            b'\x7FELF': ('elf', 'application/x-executable'),  # Linux ELF
            
            # Other
            b'{': ('json', 'application/json'),  # Simple JSON detection
            b'<?xml': ('xml', 'application/xml'),
        }
        
        if not self.btc_service.is_available:
            raise Exception("Bitcoin Core RPC not available")
    
    def __del__(self):
        """Close database connection when done"""
        if hasattr(self, 'db'):
            self.db.close()
    
    def get_last_scanned_block(self):
        """Get the highest block number that was scanned"""
        if not self.use_database:
            return None
        
        result = self.db.query(func.max(OPReturnScan.block_number)).scalar()
        return result
    
    def get_first_scanned_block(self):
        """Get the lowest block number that was scanned"""
        if not self.use_database:
            return None
        
        result = self.db.query(func.min(OPReturnScan.block_number)).scalar()
        return result
    
    def get_scan_statistics(self):
        """Get overall statistics about scanned blocks"""
        if not self.use_database:
            return None
        
        stats = self.db.query(
            func.count(OPReturnScan.id).label('total_blocks_scanned'),
            func.sum(OPReturnScan.large_op_returns_found).label('total_large_op_returns'),
            func.min(OPReturnScan.block_number).label('first_block'),
            func.max(OPReturnScan.block_number).label('last_block'),
            func.avg(OPReturnScan.large_op_returns_found).label('avg_per_block')
        ).first()
        
        return {
            'total_blocks_scanned': stats.total_blocks_scanned or 0,
            'total_large_op_returns': stats.total_large_op_returns or 0,
            'first_block': stats.first_block,
            'last_block': stats.last_block,
            'avg_per_block': float(stats.avg_per_block) if stats.avg_per_block else 0
        }
    
    def block_already_scanned(self, block_number):
        """Check if a block has already been scanned"""
        if not self.use_database:
            return False
        
        return self.db.query(OPReturnScan).filter_by(block_number=block_number).first() is not None
    
    def extract_mining_pool(self, coinbase_tx):
        """Extract mining pool information from coinbase transaction"""
        try:
            # Get the coinbase input (first input of first tx)
            if not coinbase_tx.get('vin') or len(coinbase_tx['vin']) == 0:
                return None, None
            
            coinbase_input = coinbase_tx['vin'][0]
            
            # Check if it's a coinbase transaction
            if 'coinbase' not in coinbase_input:
                return None, None
            
            # Decode the coinbase hex
            coinbase_hex = coinbase_input['coinbase']
            try:
                coinbase_bytes = bytes.fromhex(coinbase_hex)
                # Try to decode as ASCII, ignore errors
                coinbase_text = coinbase_bytes.decode('ascii', errors='ignore')
            except:
                coinbase_text = coinbase_hex
            
            # Common mining pool signatures
            pool_signatures = {
                'ViaBTC': 'ViaBTC',
                'F2Pool': 'F2Pool',
                'AntPool': 'AntPool',
                'Foundry': 'Foundry USA',
                'foundry': 'Foundry USA',
                'Binance': 'Binance Pool',
                'BTC.com': 'BTC.com',
                'Poolin': 'Poolin',
                'SlushPool': 'Slush Pool',
                'MARA': 'Marathon Digital',
                'marathon': 'Marathon Digital',
                'SpiderPool': 'SpiderPool',
                'SBI': 'SBI Crypto',
                'EMCD': 'EMCD',
                'Luxor': 'Luxor',
                'BraiinsPool': 'Braiins Pool',
                'stratum': 'Braiins Pool',
                'ckpool': 'CKPool',
                '/luckyPool/': 'luckyPool',
                'luckyPool': 'luckyPool',
                'ultimus': 'Ultimus Pool',
                'SecPool': 'SecPool',
            }
            
            # Search for pool signature in coinbase text
            coinbase_lower = coinbase_text.lower()
            for signature, pool_name in pool_signatures.items():
                if signature.lower() in coinbase_lower:
                    return pool_name, coinbase_text
            
            # If no known pool found, return unknown with coinbase text
            return 'Unknown', coinbase_text
            
        except Exception as e:
            logger.debug(f"Error extracting mining pool: {e}")
            return None, None
    
    def detect_file_type(self, data):
        """Detect file type from binary data or data URI"""
        import re
        import base64
        
        # First check if this is a data URI (e.g., data:image/png;base64,...)
        try:
            decoded = data.decode('utf-8', errors='ignore')
            data_uri_pattern = r'^data:(image|video|audio|application)/([a-zA-Z0-9\-\+\.]+);base64,(.+)$'
            match = re.match(data_uri_pattern, decoded.strip())
            if match:
                mime_category = match.group(1)
                mime_subtype = match.group(2)
                base64_data = match.group(3)
                
                # Map common MIME types to extensions
                mime_to_ext = {
                    'image/png': 'png',
                    'image/jpeg': 'jpg',
                    'image/jpg': 'jpg',
                    'image/gif': 'gif',
                    'image/webp': 'webp',
                    'image/bmp': 'bmp',
                    'image/svg+xml': 'svg',
                    'video/mp4': 'mp4',
                    'video/webm': 'webm',
                    'audio/mpeg': 'mp3',
                    'audio/mp3': 'mp3',
                    'audio/ogg': 'ogg',
                    'audio/wav': 'wav',
                    'application/pdf': 'pdf',
                    'application/json': 'json',
                }
                
                full_mime = f'{mime_category}/{mime_subtype}'
                ext = mime_to_ext.get(full_mime, mime_subtype)
                
                # Return the extension, mime type, and decoded binary data
                try:
                    decoded_binary = base64.b64decode(base64_data)
                    return ext, full_mime, decoded_binary
                except:
                    # If base64 decode fails, return the info but no decoded data
                    return ext, full_mime, None
        except:
            pass
        
        # Not a data URI, check file signatures
        for signature, (ext, mime) in self.file_signatures.items():
            if data.startswith(signature):
                return ext, mime, None
        return None, None, None
    
    def is_text(self, data):
        """Check if data is likely text"""
        try:
            # Try to decode as UTF-8
            decoded = data.decode('utf-8')
            # Check if it's printable
            printable_ratio = sum(c.isprintable() or c.isspace() for c in decoded) / len(decoded)
            return printable_ratio > 0.8, decoded
        except:
            return False, None
    
    def calculate_transaction_fee(self, tx):
        """
        Calculate transaction fee and size from transaction data.
        
        Returns: (fee, vsize, input_count, output_count)
        """
        try:
            # Get transaction size (vsize for SegWit, size for legacy)
            tx_size = tx.get('vsize', tx.get('size', 0))
            input_count = len(tx.get('vin', []))
            output_count = len(tx.get('vout', []))
            
            # Calculate total output value
            total_out = 0
            for vout in tx.get('vout', []):
                total_out += int(vout.get('value', 0) * 100000000)  # Convert BTC to sats
            
            # For block verbosity 2, we should have 'fee' field directly
            # (available in Bitcoin Core since the inputs are resolved)
            tx_fee = 0
            if 'fee' in tx:
                # Fee is negative in BTC, convert to positive satoshis
                tx_fee = int(abs(tx.get('fee', 0)) * 100000000)
            
            return tx_fee, tx_size, input_count, output_count
            
        except Exception as e:
            logger.warning(f"Error calculating transaction fee: {e}")
            return 0, 0, 0, 0
    
    def extract_op_return_from_script(self, script_hex):
        """Extract OP_RETURN data from script hex"""
        try:
            script_bytes = bytes.fromhex(script_hex)
            
            # OP_RETURN is 0x6a
            if script_bytes[0] != 0x6a:
                return None
            
            # Next byte(s) indicate the length
            if len(script_bytes) < 2:
                return None
            
            # Handle different push opcodes
            pos = 1
            if script_bytes[pos] <= 0x4b:  # Direct length (1-75 bytes)
                length = script_bytes[pos]
                pos += 1
            elif script_bytes[pos] == 0x4c:  # OP_PUSHDATA1
                length = script_bytes[pos + 1]
                pos += 2
            elif script_bytes[pos] == 0x4d:  # OP_PUSHDATA2
                length = int.from_bytes(script_bytes[pos+1:pos+3], 'little')
                pos += 3
            elif script_bytes[pos] == 0x4e:  # OP_PUSHDATA4
                length = int.from_bytes(script_bytes[pos+1:pos+5], 'little')
                pos += 5
            else:
                return None
            
            # Extract the data
            data = script_bytes[pos:pos+length]
            return data
            
        except Exception as e:
            logger.debug(f"Error extracting OP_RETURN: {e}")
            return None
    
    def save_op_return_data(self, scan_record, block_number, block_time, txid, vout_index, data, mined_by=None, tx_fee=0, tx_size=0, input_count=0, output_count=0):
        """Save OP_RETURN data to files and database"""
        # Detect file type (may return decoded data for data URIs)
        file_ext, mime_type, decoded_binary = self.detect_file_type(data)
        
        # If we got decoded binary data from a data URI, use that for saving
        save_data = decoded_binary if decoded_binary is not None else data
        
        is_text_data, decoded_text = self.is_text(data)
        
        # Convert to hex for database storage
        data_hex = data.hex()
        
        # Calculate fee rate and cost per byte
        fee_rate = (tx_fee / tx_size) if tx_size > 0 else 0
        cost_per_byte = (tx_fee / len(data)) if len(data) > 0 else 0
        
        # Check if data is too large for TEXT column (65535 bytes = 32767 bytes raw)
        # Store NULL in database for very large files, rely on filesystem
        store_raw_data = len(data) <= 32767
        if not store_raw_data:
            logger.info(f"  💾 Large file ({len(data):,} bytes) - storing metadata only, data on disk")
        
        # Save to database
        if self.use_database and scan_record:
            try:
                large_op_return = LargeOPReturn(
                    scan_id=scan_record.id,
                    block_number=block_number,
                    txid=txid,
                    vout_index=vout_index,
                    data_size=len(data),
                    raw_data=data_hex if store_raw_data else None,  # NULL for large files
                    decoded_text=decoded_text if store_raw_data and decoded_text else None,
                    file_type=file_ext or ("text" if is_text_data else "binary"),
                    mime_type=mime_type or ("text/plain" if is_text_data else "application/octet-stream"),
                    is_text=is_text_data,
                    tx_fee=tx_fee if tx_fee > 0 else None,
                    tx_size=tx_size if tx_size > 0 else None,
                    fee_rate=fee_rate if fee_rate > 0 else None,
                    cost_per_byte=cost_per_byte if cost_per_byte > 0 else None,
                    tx_input_count=input_count if input_count > 0 else None,
                    tx_output_count=output_count if output_count > 0 else None
                )
                self.db.add(large_op_return)
                self.db.commit()
            except Exception as e:
                logger.error(f"  ❌ Error saving to database: {e}")
                self.db.rollback()
        
        # Save to files
        # Create directory for this block
        block_dir = self.output_dir / f"block_{block_number}"
        block_dir.mkdir(exist_ok=True)
        
        # Base filename
        base_name = f"tx_{txid}_{vout_index}"
        
        # Create metadata
        metadata = {
            "block_number": block_number,
            "block_time": block_time.isoformat(),
            "mined_by": mined_by or "Unknown",
            "transaction_id": txid,
            "vout_index": vout_index,
            "data_size": len(data),
            "file_type": file_ext or ("text" if is_text_data else "binary"),
            "mime_type": mime_type or ("text/plain" if is_text_data else "application/octet-stream"),
            "raw_data_hex": data.hex(),
            "transaction_fee_sats": tx_fee if tx_fee > 0 else None,
            "transaction_size_vbytes": tx_size if tx_size > 0 else None,
            "fee_rate_sats_per_vbyte": round(fee_rate, 2) if fee_rate > 0 else None,
            "cost_per_byte_of_data": round(cost_per_byte, 2) if cost_per_byte > 0 else None,
            "tx_inputs": input_count if input_count > 0 else None,
            "tx_outputs": output_count if output_count > 0 else None
        }
        
        # Save metadata JSON (always - contains hex data for analysis)
        with open(block_dir / f"{base_name}_metadata.json", 'w', newline='\n') as f:
            json.dump(metadata, f, indent=2)
        
        # Check if this is a dangerous executable type
        dangerous_types = {'exe', 'elf'}
        is_dangerous = file_ext in dangerous_types
        
        # Save raw data (skip for executables - security risk)
        if not is_dangerous:
            with open(block_dir / f"{base_name}_raw.bin", 'wb') as f:
                f.write(save_data)
        
        # Save decoded text if applicable
        if is_text_data:
            with open(block_dir / f"{base_name}_decoded.txt", 'w', encoding='utf-8') as f:
                f.write(decoded_text)
            logger.info(f"  💬 Text data: {decoded_text[:100]}...")
        
        # Save as file if file type detected (skip executables)
        if file_ext:
            if is_dangerous:
                logger.warning(f"  ⚠️  Skipping all file creation for: {file_ext} (potential security risk)")
                logger.info(f"     Only metadata JSON saved (hex data preserved for analysis)")
            else:
                file_path = block_dir / f"{base_name}.{file_ext}"
                with open(file_path, 'wb') as f:
                    f.write(save_data)
                logger.info(f"  📄 File saved: {file_path.name} ({mime_type})")
                # If this was a data URI, note that we decoded it
                if decoded_binary is not None:
                    logger.info(f"  🔓 Decoded from data URI")
        
        return metadata
    
    def scan_block(self, block_number, skip_if_scanned=True):
        """Scan a single block for OP_RETURN transactions"""
        # Check if already scanned
        if skip_if_scanned and self.block_already_scanned(block_number):
            logger.info(f"⏭️  Block {block_number} already scanned, skipping")
            return 0
        
        try:
            block_hash = self.btc_service._call_rpc("getblockhash", [block_number])
            block = self.btc_service._call_rpc("getblock", [block_hash, 2])  # Verbosity 2 for full tx data
            
            block_time = datetime.fromtimestamp(block['time'])
            total_tx_count = len(block['tx'])
            found_count = 0
            
            # Extract mining pool from coinbase transaction (first tx)
            mined_by = None
            coinbase_text = None
            if len(block['tx']) > 0:
                coinbase_tx = block['tx'][0]
                mined_by, coinbase_text = self.extract_mining_pool(coinbase_tx)
                if mined_by:
                    logger.info(f"⛏️  Block mined by: {mined_by}")
            
            # Create scan record
            scan_record = None
            if self.use_database:
                scan_record = OPReturnScan(
                    block_number=block_number,
                    block_hash=block_hash,
                    block_time=block_time,
                    total_transactions=total_tx_count,
                    large_op_returns_found=0,  # Will update this later
                    mined_by=mined_by,
                    coinbase_text=coinbase_text
                )
                self.db.add(scan_record)
                self.db.commit()
            
            # Check each transaction
            for tx in block['tx']:
                txid = tx['txid']
                
                # Calculate transaction fee information once per transaction
                tx_fee, tx_size, input_count, output_count = self.calculate_transaction_fee(tx)
                
                # Check each output
                for vout_idx, vout in enumerate(tx['vout']):
                    script_hex = vout['scriptPubKey'].get('hex', '')
                    
                    # Check if it's OP_RETURN
                    if script_hex.startswith('6a'):  # OP_RETURN opcode
                        data = self.extract_op_return_from_script(script_hex)
                        
                        if data and len(data) > 83:
                            found_count += 1
                            logger.info(f"📦 Found OP_RETURN in block {block_number}, tx {txid}, vout {vout_idx}")
                            logger.info(f"  Size: {len(data)} bytes")
                            
                            # Log fee information if available
                            if tx_fee > 0:
                                fee_rate = tx_fee / tx_size if tx_size > 0 else 0
                                cost_per_byte = tx_fee / len(data) if len(data) > 0 else 0
                                logger.info(f"  Fee: {tx_fee:,} sats ({fee_rate:.2f} sats/vbyte)")
                                logger.info(f"  Cost: {cost_per_byte:.2f} sats/byte of OP_RETURN data")
                            
                            self.save_op_return_data(
                                scan_record,
                                block_number,
                                block_time,
                                txid,
                                vout_idx,
                                data,
                                mined_by,
                                tx_fee,
                                tx_size,
                                input_count,
                                output_count
                            )
            
            # Update scan record with found count
            if self.use_database and scan_record:
                scan_record.large_op_returns_found = found_count
                self.db.commit()
            
            return found_count
            
        except Exception as e:
            logger.error(f"Error scanning block {block_number}: {e}")
            if self.use_database:
                self.db.rollback()
            return 0
    
    def scan_blocks(self, start_block, end_block=None, auto_continue=False, backwards=False):
        """Scan a range of blocks"""
        # Handle backwards mode (scan backwards in time from first scanned block)
        if backwards:
            first_scanned = self.get_first_scanned_block()
            if first_scanned:
                # Scan one month backwards (~4320 blocks = 30 days * 144 blocks/day)
                end_block = first_scanned - 1
                start_block = max(0, first_scanned - 4320)
                logger.info(f"📍 Scanning backwards from first scanned block: {first_scanned}")
                logger.info(f"   Going back ~1 month ({first_scanned - start_block} blocks)")
            else:
                logger.error("📍 No previous scans found, cannot scan backwards")
                return 0
        # Handle auto-continue mode
        elif auto_continue:
            last_scanned = self.get_last_scanned_block()
            if last_scanned:
                start_block = last_scanned + 1
                logger.info(f"📍 Auto-continue from last scanned block: {last_scanned}")
            else:
                logger.info(f"📍 No previous scans found, starting from block {start_block}")
        
        # Get current block height if end not specified
        if end_block is None and not backwards:
            chain_info = self.btc_service._call_rpc("getblockchaininfo")
            end_block = chain_info['blocks']
        
        # Show current stats if database is enabled
        if self.use_database:
            stats = self.get_scan_statistics()
            if stats['total_blocks_scanned'] > 0:
                logger.info(f"📊 Previous statistics:")
                logger.info(f"   Blocks scanned: {stats['total_blocks_scanned']}")
                logger.info(f"   Large OP_RETURNs found: {stats['total_large_op_returns']}")
                logger.info(f"   Average per block: {stats['avg_per_block']:.2f}")
                print()
        
        logger.info(f"🔍 Scanning blocks {start_block} to {end_block}")
        logger.info(f"   Looking for OP_RETURN data > 83 bytes")
        logger.info(f"   Output directory: {self.output_dir.absolute()}")
        print()
        
        total_found = 0
        total_blocks = end_block - start_block + 1
        found_items = []  # Track all found OP_RETURNs for summary
        
        for block_num in range(start_block, end_block + 1):
            if block_num % 100 == 0 or block_num == start_block:
                progress = ((block_num - start_block) / total_blocks) * 100
                logger.info(f"📈 Progress: {progress:.1f}% (Block {block_num}/{end_block})")
            
            found = self.scan_block(block_num)
            total_found += found
            
            # If OP_RETURNs were found, get their details
            if found > 0 and self.use_database:
                scan_record = self.db.query(OPReturnScan).filter(
                    OPReturnScan.block_number == block_num
                ).first()
                if scan_record:
                    for op_return in scan_record.op_returns:
                        found_items.append({
                            'block': block_num,
                            'mined_by': scan_record.mined_by or "Unknown",
                            'txid': op_return.txid,
                            'size': op_return.data_size,
                            'type': op_return.file_type
                        })
        
        logger.info(f"\n✅ Scan complete!")
        logger.info(f"   Scanned {total_blocks} blocks")
        logger.info(f"   Found {total_found} OP_RETURN transactions > 83 bytes")
        
        # Display found items summary
        if found_items:
            logger.info(f"\n📋 Found OP_RETURNs in this scan:")
            logger.info(f"   {'Block':<8} {'Miner':<20} {'Size (bytes)':<12} {'Type':<10} {'Transaction ID'}")
            logger.info(f"   {'-'*8} {'-'*20} {'-'*12} {'-'*10} {'-'*64}")
            for item in found_items:
                logger.info(f"   {item['block']:<8} {item['mined_by']:<20} {item['size']:<12} {item['type']:<10} {item['txid'][:16]}...")
        
        if self.use_database:
            stats = self.get_scan_statistics()
            logger.info(f"\n📊 Overall statistics:")
            logger.info(f"   Total blocks scanned: {stats['total_blocks_scanned']}")
            logger.info(f"   Total large OP_RETURNs: {stats['total_large_op_returns']}")
            logger.info(f"   Block range: {stats['first_block']} - {stats['last_block']}")
            logger.info(f"   Average per block: {stats['avg_per_block']:.2f}")
        
        logger.info(f"\n💾 Data saved to: {self.output_dir.absolute()}")
        
        # Regenerate timeline_data.json if any OP_RETURNs were found
        if total_found > 0:
            self.regenerate_timeline_data()
        
        # Auto-sync git if enabled (check even if no new OP_RETURNs found)
        if self.auto_sync_git:
            self.sync_git_changes()
        else:
            logger.debug("Git auto-sync is disabled (set OP_RETURN_AUTO_SYNC_GIT=true or use --auto-sync-git)")
        
        return total_found
    
    def rescan_large_op_returns(self):
        """Re-scan all blocks that have large OP_RETURNs to update with new features (like fee tracking)"""
        if not self.use_database:
            logger.error("Re-scanning requires database to be enabled")
            return 0
        
        # Get all blocks that have large OP_RETURNs
        blocks_with_ops = self.db.query(OPReturnScan).filter(
            OPReturnScan.large_op_returns_found > 0
        ).order_by(OPReturnScan.block_number).all()
        
        if not blocks_with_ops:
            logger.info("No blocks with large OP_RETURNs found to re-scan")
            return 0
        
        total_blocks = len(blocks_with_ops)
        total_ops = sum(scan.large_op_returns_found for scan in blocks_with_ops)
        
        logger.info(f"\n🔄 Re-scanning blocks with large OP_RETURNs")
        logger.info("=" * 80)
        logger.info(f"Found {total_blocks} blocks with {total_ops} large OP_RETURNs")
        logger.info("This will DELETE and RE-SCAN to update with latest features (e.g., fee tracking)")
        logger.info("")
        
        # Confirm with user
        response = input("Continue with re-scan? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            logger.info("Re-scan cancelled")
            return 0
        
        logger.info("\n🚀 Starting re-scan...")
        print()
        
        rescanned_count = 0
        ops_found = 0
        
        for idx, scan in enumerate(blocks_with_ops, 1):
            block_num = scan.block_number
            
            # Show progress
            if idx % 10 == 0 or idx == 1:
                progress = (idx / total_blocks) * 100
                logger.info(f"📈 Progress: {progress:.1f}% ({idx}/{total_blocks} blocks)")
            
            try:
                # Delete the existing scan (cascades to LargeOPReturn records)
                self.db.query(LargeOPReturn).filter(
                    LargeOPReturn.scan_id == scan.id
                ).delete()
                self.db.query(OPReturnScan).filter(
                    OPReturnScan.id == scan.id
                ).delete()
                self.db.commit()
                
                # Re-scan the block
                found = self.scan_block(block_num, skip_if_scanned=False)
                ops_found += found
                rescanned_count += 1
                
            except Exception as e:
                logger.error(f"Error re-scanning block {block_num}: {e}")
                self.db.rollback()
                continue
        
        logger.info(f"\n✅ Re-scan complete!")
        logger.info(f"   Re-scanned {rescanned_count} blocks")
        logger.info(f"   Found {ops_found} OP_RETURN transactions")
        
        # Show updated statistics
        stats = self.get_scan_statistics()
        logger.info(f"\n📊 Updated statistics:")
        logger.info(f"   Total blocks scanned: {stats['total_blocks_scanned']}")
        logger.info(f"   Total large OP_RETURNs: {stats['total_large_op_returns']}")
        logger.info(f"   Block range: {stats['first_block']} - {stats['last_block']}")
        logger.info(f"   Average per block: {stats['avg_per_block']:.2f}")
        
        return rescanned_count
    
    def reinterpret_file_types(self, file_type_filter='binary'):
        """Re-interpret file types for existing OP_RETURNs
        
        Args:
            file_type_filter: Only reinterpret OP_RETURNs with this file type (default: 'binary')
        """
        if not self.use_database:
            logger.error("Reinterpretation requires database to be enabled")
            return 0
        
        # Query for OP_RETURNs with the specified file type
        op_returns = self.db.query(LargeOPReturn).filter(
            LargeOPReturn.file_type == file_type_filter
        ).all()
        
        if not op_returns:
            logger.info(f"No OP_RETURNs found with file type '{file_type_filter}'")
            return 0
        
        logger.info(f"\n🔄 Reinterpreting {len(op_returns)} OP_RETURN(s) with file type '{file_type_filter}'")
        logger.info("=" * 80)
        
        updated_count = 0
        unchanged_count = 0
        
        for op_return in op_returns:
            try:
                # Get the raw data
                raw_data = bytes.fromhex(op_return.raw_data)
                
                # Detect file type again (may decode data URIs)
                new_file_ext, new_mime_type, decoded_binary = self.detect_file_type(raw_data)
                
                # Use decoded binary if available (from data URI)
                save_data = decoded_binary if decoded_binary is not None else raw_data
                
                # Check if we found a more specific type
                if new_file_ext and new_file_ext != file_type_filter:
                    logger.info(f"\n📦 Block {op_return.block_number}, tx {op_return.txid[:16]}...")
                    logger.info(f"   Old type: {op_return.file_type}")
                    logger.info(f"   New type: {new_file_ext} ({new_mime_type})")
                    logger.info(f"   Size: {op_return.data_size} bytes")
                    
                    # Update database
                    op_return.file_type = new_file_ext
                    op_return.mime_type = new_mime_type
                    
                    # Get the scan record to get block info
                    scan_record = self.db.query(OPReturnScan).filter(
                        OPReturnScan.id == op_return.scan_id
                    ).first()
                    
                    if scan_record:
                        # Update metadata JSON file
                        block_dir = self.output_dir / f"block_{op_return.block_number}"
                        base_name = f"tx_{op_return.txid}_{op_return.vout_index}"
                        metadata_file = block_dir / f"{base_name}_metadata.json"
                        
                        if metadata_file.exists():
                            with open(metadata_file, 'r') as f:
                                metadata = json.load(f)
                            
                            metadata['file_type'] = new_file_ext
                            metadata['mime_type'] = new_mime_type
                            
                            with open(metadata_file, 'w', newline='\n') as f:
                                json.dump(metadata, f, indent=2)
                            
                            logger.info(f"   ✓ Updated metadata file")
                        
                        # Create/update the file with proper extension (skip dangerous executables)
                        dangerous_types = {'exe', 'elf'}
                        if new_file_ext not in dangerous_types:
                            new_file_path = block_dir / f"{base_name}.{new_file_ext}"
                            if not new_file_path.exists():
                                with open(new_file_path, 'wb') as f:
                                    f.write(save_data)
                                logger.info(f"   ✓ Created file: {new_file_path.name}")
                                if decoded_binary is not None:
                                    logger.info(f"   🔓 Decoded from data URI")
                        else:
                            logger.warning(f"   ⚠️  Skipping all file creation for executable: {new_file_ext} (security risk)")
                            # Remove any existing .bin file if it was created before security fix
                            bin_file = block_dir / f"{base_name}_raw.bin"
                            if bin_file.exists():
                                bin_file.unlink()
                                logger.info(f"   ✓ Removed existing .bin file for security")
                    
                    updated_count += 1
                else:
                    unchanged_count += 1
                    
            except Exception as e:
                logger.error(f"Error reinterpreting OP_RETURN {op_return.txid}: {e}")
        
        # Commit all changes
        self.db.commit()
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✅ Reinterpretation complete!")
        logger.info(f"   Updated: {updated_count}")
        logger.info(f"   Unchanged: {unchanged_count}")
        
        return updated_count
    
    def regenerate_timeline_data(self):
        """Regenerate timeline_data.json from all scanned OP_RETURN data"""
        try:
            logger.info(f"\n📊 Regenerating timeline_data.json...")
            
            # Import generate_timeline_data functions
            import sys
            from pathlib import Path
            
            # Try to import the generate_timeline_data module
            try:
                # Check if generate_timeline_data.py exists in the same directory
                script_dir = Path(__file__).parent
                generate_script = script_dir / 'generate_timeline_data.py'
                
                if generate_script.exists():
                    # Import the module dynamically
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("generate_timeline_data", generate_script)
                    generate_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(generate_module)
                    
                    # Call the scan function (pass the op_return_data directory)
                    timeline_data = generate_module.scan_op_return_data(str(self.output_dir))
                    
                    if timeline_data:
                        # Save to JSON file (in op_return_data directory)
                        output_file = self.output_dir / 'timeline_data.json'
                        import json
                        with open(output_file, 'w', newline='\n') as f:
                            json.dump(timeline_data, f, indent=2)
                        
                        logger.info(f"   ✓ Updated timeline_data.json ({len(timeline_data)} items)")
                    else:
                        logger.debug("   No timeline data to generate")
                else:
                    logger.debug(f"   generate_timeline_data.py not found at {generate_script}")
            except Exception as e:
                logger.warning(f"   ⚠️  Failed to regenerate timeline_data.json: {e}")
                logger.debug(f"   You can manually run: python generate_timeline_data.py")
        except Exception as e:
            logger.debug(f"Error regenerating timeline data: {e}")
    
    def setup_git_authentication(self):
        """Setup git authentication using GitHub token or SSH"""
        if self.github_token:
            # Use HTTPS with token - update remote URL if needed
            try:
                # Check current remote URL
                result = subprocess.run(
                    ['git', 'remote', 'get-url', 'origin'],
                    capture_output=True,
                    text=True,
                    check=False,
                    cwd=str(self.submodule_root)
                )
                
                current_url = result.stdout.strip()
                
                # If using SSH URL, convert to HTTPS
                if current_url.startswith('git@github.com:'):
                    # Convert git@github.com:user/repo.git to https://github.com/user/repo.git
                    repo_path = current_url.replace('git@github.com:', '').replace('.git', '')
                    https_url = f'https://github.com/{repo_path}.git'
                    
                    # Update remote URL
                    subprocess.run(
                        ['git', 'remote', 'set-url', 'origin', https_url],
                        check=True,
                        cwd=str(self.submodule_root)
                    )
                    logger.debug(f"   Updated remote URL to HTTPS")
                
                return True
            except Exception as e:
                logger.debug(f"Git authentication setup error: {e}")
                return False
        else:
            # Fall back to SSH if no token provided
            logger.debug("No GITHUB_TOKEN found, using SSH authentication")
            return True
    
    def sync_git_changes(self):
        """Automatically commit and push changes to the bitcoin_large_op_returns submodule"""
        if not self.submodule_root or not self.submodule_root.exists():
            logger.debug("Submodule root not found, skipping git sync")
            return
        
        git_dir = self.submodule_root / '.git'
        if not git_dir.exists():
            logger.debug(f"Not a git repository: {self.submodule_root}")
            return
        
        # Setup git authentication (HTTPS with token or SSH)
        self.setup_git_authentication()
        
        # Log that we're checking for sync
        logger.info(f"\n🔄 Checking for git changes in {self.submodule_root.name}...")
        
        try:
            # Change to submodule directory
            original_cwd = os.getcwd()
            os.chdir(str(self.submodule_root))
            
            try:
                # Check if there are any changes
                result = subprocess.run(
                    ['git', 'status', '--porcelain'],
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if not result.stdout.strip():
                    logger.info(f"   ✓ No changes to commit - repository is up to date")
                    return
                
                # Show what will be committed
                logger.info(f"   Changes detected:")
                for line in result.stdout.strip().split('\n')[:10]:  # Show first 10 files
                    logger.info(f"     {line}")
                if result.stdout.count('\n') > 10:
                    logger.info(f"     ... and {result.stdout.count('\n') - 10} more files")
                
                # Add all changes
                subprocess.run(
                    ['git', 'add', '-A'],
                    check=True,
                    capture_output=True
                )
                
                # Get count of new/changed files for commit message
                status_lines = result.stdout.strip().split('\n')
                new_files = sum(1 for line in status_lines if line.startswith('??'))
                modified_files = len(status_lines) - new_files
                
                # Create commit message
                commit_msg = f"Add OP_RETURN data: {new_files} new files"
                if modified_files > 0:
                    commit_msg += f", {modified_files} modified"
                
                # Commit
                subprocess.run(
                    ['git', 'commit', '-m', commit_msg],
                    check=True,
                    capture_output=True
                )
                logger.info(f"   ✓ Committed changes")
                
                # Push to remote (use token if available)
                push_env = os.environ.copy()
                
                if self.github_token:
                    # Use HTTPS with token - embed token in URL for this push
                    result = subprocess.run(
                        ['git', 'remote', 'get-url', 'origin'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    remote_url = result.stdout.strip()
                    
                    # Extract repo path from URL
                    if 'github.com' in remote_url:
                        if remote_url.startswith('https://'):
                            # Already HTTPS, add token
                            if '@' not in remote_url:  # No token already embedded
                                repo_path = remote_url.replace('https://github.com/', '').replace('.git', '')
                                token_url = f'https://{self.github_token}@github.com/{repo_path}.git'
                            else:
                                token_url = remote_url
                        else:
                            # SSH URL, convert to HTTPS with token
                            repo_path = remote_url.replace('git@github.com:', '').replace('.git', '')
                            token_url = f'https://{self.github_token}@github.com/{repo_path}.git'
                        
                        # Temporarily update remote URL with token, then push
                        subprocess.run(
                            ['git', 'remote', 'set-url', 'origin', token_url],
                            check=True
                        )
                        push_result = subprocess.run(
                            ['git', 'push'],
                            check=False,
                            capture_output=True,
                            text=True,
                            env=push_env
                        )
                        # Restore original URL (without token) for security
                        clean_url = remote_url.replace(f'{self.github_token}@', '') if '@' in remote_url else remote_url
                        if not clean_url.startswith('https://'):
                            clean_url = f'https://github.com/{repo_path}.git'
                        subprocess.run(
                            ['git', 'remote', 'set-url', 'origin', clean_url],
                            check=False
                        )
                        
                        # Check if token might be invalid
                        if push_result.returncode != 0:
                            error_output = push_result.stderr if push_result.stderr else push_result.stdout
                            if '403' in error_output or 'Permission denied' in error_output or 'denied' in error_output.lower():
                                logger.warning(f"   ⚠️  Authentication failed - check your GITHUB_TOKEN:")
                                logger.warning(f"      - Token must have 'repo' scope")
                                logger.warning(f"      - Token must be valid and not expired")
                                logger.warning(f"      - Set GITHUB_TOKEN in .env file")
                    else:
                        # Not GitHub, use regular push
                        push_result = subprocess.run(
                            ['git', 'push'],
                            check=False,
                            capture_output=True,
                            text=True,
                            env=push_env
                        )
                else:
                    # No token, try SSH
                    ssh_key = os.getenv('SSH_KEY_PATH', os.path.expanduser('~/.ssh/cyber64'))
                    if os.path.exists(ssh_key):
                        push_env['GIT_SSH_COMMAND'] = f'ssh -i {ssh_key} -o IdentitiesOnly=yes'
                    
                    push_result = subprocess.run(
                        ['git', 'push'],
                        check=False,
                        capture_output=True,
                        text=True,
                        env=push_env
                    )
                
                if push_result.returncode == 0:
                    logger.info(f"   ✓ Pushed to remote")
                    logger.info(f"   ✅ Git sync complete!")
                else:
                    error_msg = push_result.stderr if push_result.stderr else push_result.stdout
                    logger.warning(f"   ⚠️  Git push failed: {error_msg}")
                    if not self.github_token:
                        logger.warning(f"   Set GITHUB_TOKEN in .env file for automatic authentication")
                        logger.warning(f"   Or manually run: eval $(ssh-agent) && ssh-add ~/.ssh/cyber64")
                    elif '403' in error_msg or 'Permission denied' in error_msg or 'denied' in error_msg.lower():
                        logger.warning(f"   Authentication issue detected:")
                        logger.warning(f"   - Verify GITHUB_TOKEN has 'repo' scope")
                        logger.warning(f"   - Check token hasn't expired")
                        logger.warning(f"   - Ensure token has access to bitcoin_large_op_returns repository")
                    logger.warning(f"   Manual push: cd {self.submodule_root} && git push")
                
            finally:
                os.chdir(original_cwd)
                
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.warning(f"   ⚠️  Git sync failed: {error_msg}")
            logger.warning(f"   You may need to manually commit and push changes")
        except Exception as e:
            logger.warning(f"   ⚠️  Error during git sync: {e}")
            logger.warning(f"   You may need to manually commit and push changes")

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Scan Bitcoin blocks for OP_RETURN data > 83 bytes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Scan a single block:
    python op_return_scanner.py 917963
  
  Scan a range of blocks:
    python op_return_scanner.py 917963 918000
  
  Auto-continue from last scan:
    python op_return_scanner.py --continue
  
  Scan backwards from first scan (1 month earlier):
    python op_return_scanner.py --backwards
  
  Show statistics without scanning:
    python op_return_scanner.py --stats
  
  Reinterpret file types (update 'binary' files with new detection):
    python op_return_scanner.py --reinterpret
    python op_return_scanner.py --reinterpret text
  
  Re-scan all blocks with large OP_RETURNs (to add fee tracking, etc.):
    python op_return_scanner.py --rescan_large_op_returns
  
  Regenerate timeline_data.json from existing data:
    python op_return_scanner.py --regenerate-timeline-data-json
        """
    )
    parser.add_argument('start_block', type=int, nargs='?', help='Starting block number')
    parser.add_argument('end_block', type=int, nargs='?', help='Ending block number (optional, defaults to current height)')
    parser.add_argument('--output', '-o', default='bitcoin_large_op_returns/op_return_data', help='Output directory (default: bitcoin_large_op_returns/op_return_data)')
    parser.add_argument('--continue', '-c', dest='auto_continue', action='store_true', 
                       help='Continue forward from last scanned block')
    parser.add_argument('--backwards', '-b', action='store_true',
                       help='Scan backwards from first scanned block (~1 month, 4320 blocks)')
    parser.add_argument('--stats', '-s', action='store_true', 
                       help='Show statistics and exit')
    parser.add_argument('--reinterpret', '-r', nargs='?', const='binary', default=None, metavar='TYPE',
                       help='Reinterpret existing OP_RETURNs with specified file type (default: binary)')
    parser.add_argument('--rescan_large_op_returns', action='store_true',
                       help='Re-scan all blocks that have large OP_RETURNs (to update with new features like fee tracking)')
    parser.add_argument('--no-db', action='store_true', 
                       help='Disable database storage (files only)')
    parser.add_argument('--auto-sync-git', action='store_true',
                       help='Automatically commit and push changes to git submodule (can also set OP_RETURN_AUTO_SYNC_GIT=true)')
    parser.add_argument('--no-auto-sync-git', action='store_true',
                       help='Disable automatic git sync (overrides environment variable)')
    parser.add_argument('--regenerate-timeline-data-json', action='store_true',
                       help='Regenerate timeline_data.json from existing OP_RETURN data and exit')
    
    args = parser.parse_args()
    
    try:
        auto_sync = args.auto_sync_git if args.auto_sync_git else (False if args.no_auto_sync_git else None)
        scanner = OPReturnScanner(output_dir=args.output, use_database=not args.no_db, auto_sync_git=auto_sync)
        
        # Show stats and exit
        if args.stats:
            if not args.no_db:
                stats = scanner.get_scan_statistics()
                print("\n📊 OP_RETURN Scan Statistics")
                print("=" * 50)
                print(f"Total blocks scanned:     {stats['total_blocks_scanned']}")
                print(f"Total large OP_RETURNs:   {stats['total_large_op_returns']}")
                if stats['first_block']:
                    print(f"Block range:              {stats['first_block']} - {stats['last_block']}")
                print(f"Average per block:        {stats['avg_per_block']:.2f}")
                print()
            else:
                logger.error("Stats require database mode (don't use --no-db)")
            return 0
        
        # Reinterpret file types and exit
        if args.reinterpret is not None:
            if not args.no_db:
                scanner.reinterpret_file_types(args.reinterpret)
            else:
                logger.error("Reinterpretation requires database mode (don't use --no-db)")
            return 0
        
        # Re-scan all blocks with large OP_RETURNs and exit
        if args.rescan_large_op_returns:
            if not args.no_db:
                scanner.rescan_large_op_returns()
            else:
                logger.error("Re-scanning requires database mode (don't use --no-db)")
            return 0
        
        # Regenerate timeline_data.json and exit
        if args.regenerate_timeline_data_json:
            scanner.regenerate_timeline_data()
            return 0
        
        # Require start_block unless using --continue or --backwards
        if not args.auto_continue and not args.backwards and args.start_block is None:
            parser.error("start_block is required unless using --continue or --backwards")
        
        # Set default start block for auto-continue or backwards
        if args.auto_continue or args.backwards:
            if args.start_block is None:
                args.start_block = 0  # Will be overridden by auto_continue or backwards
        
        scanner.scan_blocks(args.start_block, args.end_block, 
                          auto_continue=args.auto_continue, 
                          backwards=args.backwards)
    except Exception as e:
        logger.error(f"Scanner failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())

