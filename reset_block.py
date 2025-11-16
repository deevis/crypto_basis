"""Reset a block to allow re-scanning"""
import sys
from db_config import SessionLocal
from models import OPReturnScan, LargeOPReturn

if len(sys.argv) < 2:
    print("Usage: python reset_block.py <block_number>")
    sys.exit(1)

block_number = int(sys.argv[1])
db = SessionLocal()

try:
    scan = db.query(OPReturnScan).filter_by(block_number=block_number).first()
    if scan:
        # First delete the associated large_op_returns records
        op_returns_count = db.query(LargeOPReturn).filter_by(scan_id=scan.id).count()
        db.query(LargeOPReturn).filter_by(scan_id=scan.id).delete()
        
        # Then delete the scan record
        db.delete(scan)
        db.commit()
        print(f"[OK] Block {block_number} deleted from database ({op_returns_count} OP_RETURNs removed), ready to re-scan")
    else:
        print(f"[INFO] Block {block_number} not in database")
except Exception as e:
    db.rollback()
    print(f"[ERROR] Failed to delete block {block_number}: {e}")
    sys.exit(1)
finally:
    db.close()

