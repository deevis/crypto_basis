import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine, SessionLocal
from models import ExchangeTransfer, CapitalGainsTerm

def migrate():
    # Add the column
    with engine.connect() as connection:
        try:
            connection.execute(text("""
                ALTER TABLE exchange_transfers
                ADD COLUMN term_type ENUM('SHORT', 'LONG')
            """))
            print("Added term_type column")
            
        except Exception as e:
            print(f"Error adding column: {e}")
    
    # Backfill existing data
    session = SessionLocal()
    try:
        transfers = session.query(ExchangeTransfer).filter(
            ExchangeTransfer.sale_date.isnot(None)
        ).all()
        
        for transfer in transfers:
            transfer.term_type = transfer.calculate_term_type(session)
        
        session.commit()
        print("Backfilled term_type data")
        
    except Exception as e:
        session.rollback()
        print(f"Error backfilling data: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    migrate() 