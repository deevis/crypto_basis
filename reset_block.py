"""Reset a block to allow re-scanning"""
import sys
from pathlib import Path
from db_config import SessionLocal
from models import OPReturnScan, LargeOPReturn

if len(sys.argv) < 2:
    print("Usage: python reset_block.py <block_number>")
    sys.exit(1)

block_number = int(sys.argv[1])
db = SessionLocal()

# Default output directory (same as OPReturnScanner)
output_dir = Path("bitcoin_large_op_returns/op_return_data")
block_dir = output_dir / f"block_{block_number}"

try:
    scan = db.query(OPReturnScan).filter_by(block_number=block_number).first()
    if scan:
        # First delete the associated large_op_returns records
        op_returns_count = db.query(LargeOPReturn).filter_by(scan_id=scan.id).count()
        db.query(LargeOPReturn).filter_by(scan_id=scan.id).delete()
        
        # Then delete the scan record
        db.delete(scan)
        db.commit()
        print(f"[OK] Block {block_number} deleted from database ({op_returns_count} OP_RETURNs removed)")
    else:
        print(f"[INFO] Block {block_number} not in database")
    
    # Delete from filesystem if directory exists
    if block_dir.exists() and block_dir.is_dir():
        import shutil
        try:
            shutil.rmtree(block_dir)
            print(f"[OK] Block {block_number} deleted from filesystem: {block_dir}")
        except Exception as fs_error:
            print(f"[WARNING] Failed to delete filesystem directory {block_dir}: {fs_error}")
    else:
        print(f"[INFO] Block {block_number} not found in filesystem: {block_dir}")
    
    print(f"[OK] Block {block_number} reset complete, ready to re-scan")
    
except Exception as e:
    db.rollback()
    print(f"[ERROR] Failed to delete block {block_number}: {e}")
    sys.exit(1)
finally:
    db.close()

