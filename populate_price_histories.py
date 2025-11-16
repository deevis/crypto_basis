import logging
from datetime import datetime, timedelta
import time
import os
import csv
import argparse
from db_config import SessionLocal
from models import Transaction, CoinPrice
from price_service import PriceService
from sqlalchemy import func
from btc_service import BTCService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def load_price_history_from_csv(session, filename):
    """Load price history from a CSV file"""
    try:
        coin = os.path.basename(filename).split('_')[0].upper()
        
        # First, peek at the CSV to get date range
        with open(filename, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                logger.warning(f"Empty CSV file: {filename}")
                return
                
            # Get first and last dates from CSV
            csv_dates = sorted([datetime.strptime(row['date'], '%Y-%m-%d').date() for row in rows])
            earliest_csv_date = csv_dates[0]
            latest_csv_date = csv_dates[-1]
            
            # Check if we already have prices for these boundary dates
            boundary_prices = session.query(CoinPrice).filter(
                CoinPrice.ticker == coin,
                CoinPrice.price_date.in_([earliest_csv_date, latest_csv_date])
            ).count()
            
            if boundary_prices == 2:
                logger.info(f"Skipping {filename} - boundary dates already exist in database")
                return
            
            logger.info(f"Loading price history from {filename}")
            loaded_count = 0
            
            # Process rows if we need to
            for row in rows:
                try:
                    date = datetime.strptime(row['date'], '%Y-%m-%d').date()
                    price = float(row['avg_price_usd'])
                    
                    # Check if we already have this price
                    existing = session.query(CoinPrice).filter(
                        CoinPrice.ticker == coin,
                        CoinPrice.price_date == date
                    ).first()
                    
                    if not existing:
                        price_record = CoinPrice(
                            ticker=coin,
                            price_date=date,
                            price_usd=price,
                            source='csv_import'
                        )
                        session.add(price_record)
                        loaded_count += 1
                        
                        if loaded_count % 100 == 0:
                            session.commit()
                            logger.info(f"Loaded {loaded_count} prices for {coin}")
                
                except (ValueError, KeyError) as e:
                    logger.warning(f"Error processing row in {filename}: {e}")
                    continue
            
            session.commit()
            logger.info(f"Completed loading {loaded_count} prices for {coin}")
            
    except Exception as e:
        logger.error(f"Error processing file {filename}: {e}")
        session.rollback()

def populate_missing_block_info():
    """Populate block info for BTC transactions that are missing it"""
    print("Checking for BTC transactions missing block info...")
    
    db = SessionLocal()
    
    try:
        # Find BTC transactions with hash but no block number
        missing_block_info = db.query(Transaction).filter(
            Transaction.currency_ticker == "BTC",
            Transaction.operation_hash.isnot(None),
            Transaction.block_number.is_(None)
        ).all()
        
        if missing_block_info:
            print(f"Found {len(missing_block_info)} transactions missing block info")
            
            try:
                # Try to initialize BTC service
                btc_service = BTCService()
                
                # Test connection to Bitcoin Core
                try:
                    btc_service._call_rpc("getblockchaininfo")
                    connected = True
                except Exception as e:
                    print(f"Warning: Cannot connect to Bitcoin Core RPC: {e}")
                    print("Skipping block info updates - will try again next time")
                    connected = False
                
                if connected:
                    for tx in missing_block_info:
                        try:
                            if btc_service.update_transaction_block_info(tx):
                                print(f"Updated block info for transaction {tx.operation_hash}")
                        except Exception as tx_e:
                            print(f"Error updating block info for tx {tx.operation_hash}: {tx_e}")
                            # Continue with next transaction
                            continue
                    
                    db.commit()
                    print("Block info update complete")
            except Exception as e:
                print(f"Warning: BTC service initialization failed: {e}")
                print("Skipping block info updates - will try again next time")
        else:
            print("No transactions missing block info")
            
    except Exception as e:
        print(f"Error checking for missing block info: {e}")
        db.rollback()
    finally:
        db.close()

def populate_price_histories():
    session = SessionLocal()
    price_service = PriceService()
    
    try:
        # First, load any CSV files from data/price_histories
        price_history_dir = os.path.join('data', 'price_histories')
        if os.path.exists(price_history_dir):
            for filename in os.listdir(price_history_dir):
                if filename.endswith('.csv'):
                    full_path = os.path.join(price_history_dir, filename)
                    load_price_history_from_csv(session, full_path)
        
        # Get unique coins and their earliest transaction dates
        coin_ranges = session.query(
            Transaction.currency_ticker,
            func.min(Transaction.operation_date).label('earliest_date')
        ).group_by(Transaction.currency_ticker).all()
        
        today = datetime.now().date()
        
        for coin, earliest_date in coin_ranges:
            logger.info(f"Processing {coin} from {today} back to {earliest_date}")
            
            # Get existing price dates for this coin
            existing_dates = set(
                d[0].date() for d in session.query(CoinPrice.price_date)
                .filter(CoinPrice.ticker == coin)
                .all()
            )
            
            # Ensure we have coin ID mapping
            coin_id = price_service.get_coingecko_id(coin)
            if not coin_id:
                logger.warning(f"No CoinGecko mapping found for {coin} - please add to PriceService.coin_map")
                continue
            
            # skip MATIC as it is no longer supported by CoinGecko
            if coin == 'MATIC':
                continue

            # Process each date backwards from today
            current_date = today
            earliest_date = earliest_date.date()
            days_processed = 0
            
            while current_date >= earliest_date and days_processed < 365:
                if current_date not in existing_dates:
                    retry_count = 0
                    while retry_count < 3:  # Allow up to 3 retries
                        try:
                            logger.info(f"Fetching price for {coin} on {current_date}")
                            price = price_service.get_historical_price(coin, current_date)
                            
                            if price:
                                price_record = CoinPrice(
                                    ticker=coin,
                                    price_date=current_date,
                                    price_usd=price,
                                    source='coingecko'
                                )
                                session.add(price_record)
                                session.commit()
                                logger.info(f"Added price for {coin} on {current_date}: ${price:,.2f}")
                            else:
                                logger.warning(f"No price found for {coin} on {current_date}")
                            break  # Success, exit retry loop
                            
                        except Exception as e:
                            if "429" in str(e) or "Rate Limit" in str(e):
                                retry_count += 1
                                wait_time = 30  # Base wait time in seconds
                                total_wait = wait_time * retry_count
                                logger.warning(f"Rate limit hit, waiting {total_wait} seconds before retry {retry_count}/3")
                                time.sleep(total_wait)
                                continue
                            else:
                                logger.error(f"Error fetching {coin} price for {current_date}: {str(e)}")
                                session.rollback()
                                break
                    
                    # Respect rate limits for next request
                    time.sleep(12.2)  # A bit more than 12 seconds to be safe - coingecko free tier limit
                
                current_date -= timedelta(days=1)
                days_processed += 1
            
            if current_date >= earliest_date:
                logger.warning(f"Reached 365 day limit for {coin}. Earliest date processed: {current_date}")
            
            logger.info(f"Completed processing {coin}")
    
    finally:
        session.close()

def dump_price_data(ticker):
    """Dump all historical price data for a specific ticker to a CSV file"""
    session = SessionLocal()
    
    try:
        # Query all price data for the specified ticker
        price_data = session.query(CoinPrice).filter(
            CoinPrice.ticker == ticker.upper()
        ).order_by(CoinPrice.price_date).all()
        
        if not price_data:
            logger.warning(f"No price data found for {ticker}")
            return
        
        # Create filename with date range
        earliest_date = price_data[0].price_date
        latest_date = price_data[-1].price_date
        # make sure the dates are in the format YYYY-MM-DD
        earliest_date = earliest_date.strftime('%Y-%m-%d')
        latest_date = latest_date.strftime('%Y-%m-%d')
        filename = f"data/dumps/{ticker.lower()}_dump_{earliest_date}_{latest_date}.csv"
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Write to CSV file
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['date', 'price_usd', 'source']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for price_record in price_data:
                writer.writerow({
                    'date': price_record.price_date.strftime('%Y-%m-%d'),
                    'price_usd': price_record.price_usd,
                    'source': price_record.source
                })
        
        logger.info(f"Dumped {len(price_data)} price records for {ticker} to {filename}")
        print(f"Price data dumped to: {filename}")
        
    except Exception as e:
        logger.error(f"Error dumping price data for {ticker}: {e}")
        raise
    finally:
        session.close()

def main():
    parser = argparse.ArgumentParser(description='Populate or dump historical price data')
    parser.add_argument('command', nargs='?', default='populate', 
                       help='Command to run: populate (default) or dump')
    parser.add_argument('ticker', nargs='?', 
                       help='Ticker symbol (required for dump command)')
    
    args = parser.parse_args()
    
    if args.command == 'dump':
        if not args.ticker:
            parser.error("Ticker symbol is required for dump command")
        
        logger.info(f"Dumping price data for {args.ticker}")
        dump_price_data(args.ticker)
        
    elif args.command == 'populate' or not args.command:
        logger.info("Starting price history population")
        try:
            populate_missing_block_info()
            populate_price_histories()
            logger.info("Price history population completed successfully")
        except Exception as e:
            logger.error(f"Error during price history population: {str(e)}")
            raise
    else:
        parser.error(f"Unknown command: {args.command}")

if __name__ == "__main__":
    main() 