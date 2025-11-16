import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db_config import engine, SessionLocal
from models import ExchangeTransfer

def migrate():
    # Add the columns
    with engine.connect() as connection:
        try:
            connection.execute(text("""
                ALTER TABLE exchange_transfers
                ADD COLUMN acquisition_price FLOAT,
                ADD COLUMN acquisition_date DATETIME
            """))
            print("Added acquisition details columns")
            
        except Exception as e:
            print(f"Error adding columns: {e}")
    
    # Backfill existing data
    session = SessionLocal()
    try:
        transfers = session.query(ExchangeTransfer).filter(
            ExchangeTransfer.sale_date.isnot(None)
        ).all()
        
        for transfer in transfers:
            acq_price, acq_date = transfer.calculate_acquisition_details(session)
            transfer.acquisition_price = acq_price
            transfer.acquisition_date = acq_date
        
        session.commit()
        print("Backfilled acquisition details")
        
    except Exception as e:
        session.rollback()
        print(f"Error backfilling data: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    migrate() 