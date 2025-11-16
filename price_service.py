import json
import requests
from typing import Dict
import time
import logging
import random
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from db_config import SessionLocal
from models import CoinPrice, Transaction
from sqlalchemy.sql import func

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PriceService:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        self.api_key = os.getenv("COINGECKO_API_KEY")
        if not self.api_key:
            logger.warning("No CoinGecko API key found in environment variables")
            
        self.source = "coingecko"
        self.base_url = "https://api.coingecko.com/api/v3"
        self.price_cache = {}
        self.cache_timestamp = 0
        self.cache_duration = 600  # Cache prices for 10 minutes
        
        # Map our coin symbols to CoinGecko IDs
        self.coin_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "ALGO": "algorand",
            "BCH": "bitcoin-cash",
            "DOGE": "dogecoin",
            "LTC": "litecoin",
            "XRP": "ripple",
            "ADA": "cardano",
            "SOL": "solana",
            "DOT": "polkadot",
            "LINK": "chainlink",
            "XTZ": "tezos",
            "XLM": "stellar",
            "XMR": "monero",
            "ZEC": "zcash",
            "AMP": "amp-token",
            "AXS": "axie-infinity",
            "FIL": "filecoin",
            "GRT": "the-graph",
            "HBAR": "hedera-hashgraph",
            "ICP": "internet-computer",
            "KSM": "kusama",
            "LDO": "lido-dao",
            "BAT": "basic-attention-token",
            "SAND": "the-sandbox",
            "GALA": "gala",
            "MANA": "decentraland",
            "OMG": "omisego",
            "POL": "polygon-ecosystem-token",
            "QNT": "quant-network",
            "SHIB": "shiba-inu",
            "ZRX": "0x",
            "MATIC": "matic-network",
            
            # Add more mappings as needed
        }
    
    def get_current_prices(self, coins: list) -> Dict[str, float]:
        """Get current prices for multiple coins in USD"""
        current_time = time.time()
        
        # If cache is still valid, use it
        if current_time - self.cache_timestamp < self.cache_duration:
            logger.debug(f"Using cached prices from {int(current_time - self.cache_timestamp)} seconds ago")
            return self.price_cache
        
        # Convert our symbols to CoinGecko IDs
        coin_ids = [self.coin_map.get(coin) for coin in coins if coin in self.coin_map]
        
        if not coin_ids:
            return {}
        
        max_retries = 5
        base_delay = 2  # Start with 2 second delay
        
        for attempt in range(max_retries):
            try:
                coin_ids = ",".join(coin_ids)
                logger.info(f"Fetching prices for {coins} (Attempt {attempt + 1}/{max_retries})")
                logger.info(f"Coin IDs: {coin_ids}")
                
                headers = {"X-CG-API-KEY": self.api_key} if self.api_key else {}
                
                response = requests.get(
                    f"{self.base_url}/simple/price",
                    params={
                        "ids": coin_ids,
                        "vs_currencies": "usd"
                    },
                    headers=headers
                )
                response.raise_for_status()
                
                # Log response details
                logger.info(f"API Response: {response.text}")
                
                # Convert response to our format
                prices = {}
                data = response.json()
                for coin in coins:
                    if coin in self.coin_map and self.coin_map[coin] in data:
                        coin_data = data[self.coin_map[coin]]
                        if "usd" in coin_data:
                            prices[coin] = coin_data["usd"]
                            logger.info(f"Price for {coin}: ${prices[coin]:.2f}")
                        else:
                            logger.warning(f"No USD price available for {coin} (ID: {self.coin_map[coin]})")
                
                # Update cache
                self.price_cache = prices
                self.cache_timestamp = current_time

                # every time we fetch prices, we'll archive the current prices to a file
                self.archive_current_prices(current_time, prices)
                
                return prices
                
            except requests.exceptions.RequestException as e:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"API request failed: {str(e)}")
                logger.info(f"Retrying in {delay:.1f} seconds...")
                time.sleep(delay)
        
        logger.error("Failed to fetch prices after all retries")
        return {}
    
    def archive_current_prices(self, current_time, prices):
        """Archive current prices to a file"""
        # convert current_time to YYYY-MM-DD HH:MM:SS
        time_string = datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:%S')
        data = { "time": time_string, "source": self.source, "prices": prices }
        with open('data/current_prices.json', 'w', newline='\n') as f:
            json.dump(data, f)
    
    
    def warm_cache(self):
        """Pre-fetch all known coin prices"""
        logger.info("Warming price cache...")
        all_coins = list(self.coin_map.keys())
        
        # Split coins into smaller groups to avoid rate limits
        group_size = 40
        for i in range(0, len(all_coins), group_size):
            coin_group = all_coins[i:i + group_size]
            logger.info(f"Fetching prices for group: {coin_group}")
            self.get_current_prices(coin_group)
            # Add delay between groups
            if i + group_size < len(all_coins):
                delay = random.uniform(2, 3)
                logger.info(f"Waiting {delay:.1f} seconds before next group...")
                time.sleep(delay)
    
    def fetch_missing_prices(self):
        """Fetch missing prices for all coins in transactions"""
        session = SessionLocal()
        try:
            # Get unique coins and their date ranges
            coins = session.query(
                Transaction.currency_ticker,
                func.min(Transaction.operation_date).label('start_date'),
                func.max(Transaction.operation_date).label('end_date')
            ).group_by(Transaction.currency_ticker).all()
            
            for coin, start_date, end_date in coins:
                # Get existing price dates for this coin
                existing_dates = set(
                    d[0] for d in session.query(CoinPrice.price_date)
                    .filter(CoinPrice.ticker == coin)
                    .all()
                )
                
                # Generate list of dates needed
                current_date = start_date.date()
                end_date = end_date.date()
                
                while current_date <= end_date:
                    if current_date not in existing_dates:
                        try:
                            price = self.get_historical_price(coin, current_date)
                            if price:
                                session.add(CoinPrice(
                                    ticker=coin,
                                    price_date=current_date,
                                    price_usd=price,
                                    source='coingecko'
                                ))
                        except Exception as e:
                            logger.error(f"Error fetching price for {coin} on {current_date}: {e}")
                    
                    current_date += timedelta(days=1)
                
                session.commit()
                
        finally:
            session.close()
    
    def get_historical_price(self, coin, date):
        """Get historical price for a coin on a specific date"""
        # Convert BTC ticker to coingecko ID
        coin_id = self.get_coingecko_id(coin)
        
        date_str = date.strftime('%d-%m-%Y')
        url = f"{self.base_url}/coins/{coin_id}/history"
        
        response = requests.get(url, params={
            'date': date_str,
            'localization': 'false'
        })
        
        if response.status_code == 200:
            data = response.json()
            return data['market_data']['current_price']['usd']
        else:
            raise Exception(f"Failed to get price: {response.text}")
    
    def get_coingecko_id(self, ticker):
        """Convert ticker to CoinGecko ID"""
        return self.coin_map.get(ticker) 