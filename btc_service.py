import os
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta
import json
import logging
from transaction_details_dialog import TransactionDetailsDialog
from decimal import Decimal
import urllib.parse

# Configure logging with timestamp and level
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class BTCService:
    def __init__(self, test_connection=True):
        load_dotenv()
        self.host = os.getenv('BTC_RPC_HOST', 'localhost')
        self.port = os.getenv('BTC_RPC_PORT', '8332')
        self.user = os.getenv('BTC_RPC_USER')
        self.password = os.getenv('BTC_RPC_PASSWORD')
        # Get wallet name from environment, default to the legacy wallet
        self.wallet_name = os.getenv('BTC_WALLET_NAME', 'crypto-basis-legacy')
        # Get wallet directory from environment, or empty string for non-path wallets
        self.wallet_dir = os.getenv('BTC_WALLET_DIR', '')
        
        # Use proper path separator for the OS
        self.wallet_path = os.path.join(self.wallet_dir, self.wallet_name)
        
        logger.debug(f"Initialized BTCService with:")
        logger.debug(f"  Host: {self.host}")
        logger.debug(f"  Port: {self.port}")
        logger.debug(f"  User: {'set' if self.user else 'not set'}")
        logger.debug(f"  Password: {'set' if self.password else 'not set'}")
        logger.debug(f"  Wallet Path: {self.wallet_path}")
        
        self.progress_callback = None
        self.is_available = False
        
        # Test connection if requested
        if test_connection:
            try:
                self._call_rpc("getblockchaininfo", timeout=5)  # Short timeout for startup
                self.is_available = True
                logger.info("Successfully connected to Bitcoin Core")
            except Exception as e:
                logger.warning(f"Bitcoin Core RPC not available: {e}")
                self.is_available = False

    def load_watch_wallet(self):
        """Load or create the watch-only wallet when needed"""
        try:
            # First check if wallet is already loaded
            try:
                wallets = self._call_rpc("listwallets")
                if self.wallet_path in wallets:
                    logger.info(f"Wallet {self.wallet_path} is already loaded")
                    return
            except Exception as e:
                logger.debug(f"Could not check loaded wallets: {e}")
            
            # Try to load the wallet
            logger.debug(f"Attempting to load wallet: {self.wallet_path}")
            self._call_rpc("loadwallet", [self.wallet_path])
            logger.info(f"Loaded existing wallet: {self.wallet_path}")
        except Exception as e:
            error_text = str(e)
            logger.debug(f"Load wallet error: {error_text}")
            
            # Check if wallet is already loaded (this is fine)
            if "is already loaded" in error_text or "already loaded" in error_text:
                logger.info("Wallet is already loaded - continuing")
                return
            
            # Check for various "wallet doesn't exist" error messages
            if any(msg in error_text for msg in [
                "not found",
                "Path does not exist",
                "Failed to load database path"
            ]):
                logger.info(f"Wallet not found, attempting to create new wallet: {self.wallet_path}")
                try:
                    self._call_rpc("createwallet", [
                        self.wallet_path,    # wallet path
                        True,               # disable private keys (watch-only)
                        False,              # blank wallet
                        "",                # passphrase
                        False,             # avoid reuse
                        False,             # descriptors - set to False for legacy wallet
                        True               # load on startup
                    ])
                    logger.info(f"Created new watch-only wallet: {self.wallet_path}")
                except Exception as create_error:
                    logger.error(f"Failed to create wallet: {create_error}")
                    raise
            else:
                logger.error(f"Failed to load wallet with unexpected error: {e}")
                raise

    def check_connection(self):
        """Check if Bitcoin Core RPC is available"""
        try:
            self._call_rpc("getblockchaininfo", timeout=5)
            self.is_available = True
            return True
        except Exception as e:
            logger.warning(f"Bitcoin Core RPC not available: {e}")
            self.is_available = False
            return False

    def _call_rpc(self, method, params=None, timeout=30):
        """Make RPC call to Bitcoin Core"""
        url = f"http://{self.host}:{self.port}"
        
        # Add wallet name to URL for wallet-specific calls
        wallet_methods = ["importaddress", "importmulti", "listunspent", "getaddressinfo", "listreceivedbyaddress", "getwalletinfo"]
        if method in wallet_methods:
            # URL encode the wallet path to handle backslashes and special characters
            encoded_wallet_path = urllib.parse.quote(self.wallet_path)
            url = f"{url}/wallet/{encoded_wallet_path}"
        
        headers = {'content-type': 'application/json'}
        payload = {
            "jsonrpc": "1.0",
            "id": "crypto-basis",
            "method": method,
            "params": params or []
        }
        
        auth = (self.user, self.password)
        
        logger.debug(f"Making RPC call: {method}")
        logger.debug(f"Params: {params}")
        
        response = requests.post(url, json=payload, headers=headers, auth=auth, timeout=timeout)
        
        if response.status_code != 200:
            logger.error(f"RPC call failed with status {response.status_code}")
            logger.error(f"Response text: {response.text}")
            raise Exception(f"RPC call failed: {response.text}")
        
        result = response.json()
        
        if result.get('error'):
            logger.error(f"Error in RPC call: {result['error']}")
            raise Exception(f"RPC call failed: {result['error']}")
        
        return result.get('result')

    def get_transaction_details(self, address, expected_date=None, txid=None):
        """
        Get details about transactions involving this address
        If txid is provided, verify just that transaction instead of scanning blocks
        """
        logger.info(f"Getting transaction details for address: {address}, txid: {txid}")
        
        try:
            if txid and txid.strip():  # Make sure we have a non-empty txid
                if self.progress_callback:
                    self.progress_callback("Looking up transaction by ID...")
                
                try:
                    logger.info(f"Attempting direct txid lookup: {txid}")
                    # Get transaction details directly - this should be near instant
                    tx = self._call_rpc("getrawtransaction", [txid, True])
                    
                    # Verify address is in outputs
                    amount = 0
                    found = False
                    for vout in tx['vout']:
                        # Check both old and new format
                        script_pub_key = vout['scriptPubKey']
                        output_addresses = []
                        
                        # New format (single address)
                        if 'address' in script_pub_key:
                            output_addresses.append(script_pub_key['address'])
                        # Old format (multiple addresses)
                        elif 'addresses' in script_pub_key:
                            output_addresses.extend(script_pub_key['addresses'])
                        
                        logger.debug(f"Output addresses: {output_addresses}")
                        
                        if address in output_addresses:
                            amount = vout['value']
                            found = True
                            break
                    
                    if not found:
                        logger.warning(f"Address {address} not found in transaction {txid}")
                        
                        # Show transaction details dialog
                        dialog = TransactionDetailsDialog(tx, address)
                        if dialog.exec() == QDialog.DialogCode.Accepted:
                            # User chose to force accept this transaction
                            logger.info("User forced acceptance of transaction")
                            result = {
                                'txid': txid,
                                'amount': amount,  # Will be 0
                                'date': datetime.fromtimestamp(tx['time']),
                                'confirmations': self._call_rpc("getblock", [tx['blockhash']])['height'] - self._call_rpc("getblock", [tx['blockhash']])['height'] + 1,
                                'block_hash': tx['blockhash']
                            }
                            return result
                        else:
                            raise ValueError(f"Address {address} not found in transaction outputs")
                    
                    # Get current height for confirmations
                    chain_info = self._call_rpc("getblockchaininfo")
                    current_height = chain_info['blocks']
                    tx_height = self._call_rpc("getblock", [tx['blockhash']])['height']
                    confirmations = current_height - tx_height + 1
                    
                    result = {
                        'txid': txid,
                        'amount': amount,
                        'date': datetime.fromtimestamp(tx['time']),
                        'confirmations': confirmations,
                        'block_hash': tx['blockhash']
                    }
                    
                    logger.info(f"Successfully found transaction by ID: {result}")
                    return result
                    
                except Exception as e:
                    logger.error(f"Direct txid lookup failed: {str(e)}")
                    # Don't fall back to scanning, just raise the error
                    raise ValueError(f"Transaction lookup failed: {str(e)}")
            
            # Only do block scanning if no txid provided
            return self._scan_blocks_for_transaction(address, expected_date)
            
        except Exception as e:
            logger.error(f"Error getting transaction details: {str(e)}")
            raise
    
    def _scan_blocks_for_transaction(self, address, expected_date=None):
        """Separated block scanning logic for clarity"""
        if self.progress_callback:
            self.progress_callback(f"Starting scan for address: {address}")
        
        logger.info(f"Getting transaction details for address: {address}")
        logger.info(f"Expected date: {expected_date}")
        
        try:
            # Get current blockchain info
            chain_info = self._call_rpc("getblockchaininfo")
            current_height = chain_info['blocks']
            logger.info(f"Current block height: {current_height}")
            
            # Determine how far back to scan
            if expected_date:
                # Bitcoin averages 6 blocks per hour
                hours_diff = (datetime.now() - expected_date).total_seconds() / 3600
                blocks_to_scan = int(hours_diff * 6) + 144  # Add 24 hours worth of blocks as buffer
                blocks_to_scan = min(blocks_to_scan, 2016)  # Cap at 2 weeks of blocks
                logger.info(f"Hours difference: {hours_diff:.1f}, will scan {blocks_to_scan} blocks")
            else:
                blocks_to_scan = 144  # Default to 24 hours if no date provided
            
            start_height = max(0, current_height - blocks_to_scan)
            logger.info(f"Scanning blocks from {current_height} back to {start_height}")
            
            # Try to optimize by getting block timestamps first
            target_timestamp = expected_date.timestamp() if expected_date else None
            
            # Get block hash for every 100 blocks to check timestamps
            if target_timestamp:
                logger.info(f"Target timestamp: {target_timestamp} ({expected_date})")
                for height in range(current_height, start_height, -100):
                    block_hash = self._call_rpc("getblockhash", [height])
                    block_header = self._call_rpc("getblockheader", [block_hash])
                    block_time = block_header['time']
                    
                    logger.debug(f"Block {height} time: {datetime.fromtimestamp(block_time)}")
                    
                    if block_time < target_timestamp:
                        # We've gone back far enough, adjust start_height
                        start_height = height
                        logger.info(f"Found starting point at block {height}")
                        break
            
            if self.progress_callback:
                self.progress_callback(f"Scanning {blocks_to_scan} blocks for transactions")
            
            # Scan blocks in reverse order
            for height in range(current_height, start_height, -1):
                if height % 10 == 0:
                    msg = f"Scanning block {height} ({current_height - height + 1}/{blocks_to_scan})"
                    if self.progress_callback:
                        # If callback returns False, abort the scan
                        if not self.progress_callback(msg):
                            raise ValueError("Scan aborted by user")
                
                block_hash = self._call_rpc("getblockhash", [height])
                block = self._call_rpc("getblock", [block_hash, 2])
                
                block_time = datetime.fromtimestamp(block['time'])
                logger.debug(f"Block {height} has {len(block['tx'])} transactions, time: {block_time}")
                
                # Check each transaction in the block
                for tx in block['tx']:
                    # Check transaction outputs
                    for vout in tx['vout']:
                        # Check both old and new format
                        script_pub_key = vout['scriptPubKey']
                        output_addresses = []
                        
                        # New format (single address)
                        if 'address' in script_pub_key:
                            output_addresses.append(script_pub_key['address'])
                        # Old format (multiple addresses)
                        elif 'addresses' in script_pub_key:
                            output_addresses.extend(script_pub_key['addresses'])
                        
                        logger.debug(f"Output addresses: {output_addresses}")
                        
                        if address in output_addresses:
                            logger.info(f"Found matching transaction: {tx['txid']} in block {height}")
                            
                            result = {
                                'txid': tx['txid'],
                                'amount': vout['value'],
                                'date': block_time,
                                'confirmations': current_height - height + 1,
                                'block_hash': block_hash
                            }
                            
                            logger.info(f"Transaction details: {result}")
                            return result
            
            logger.warning(f"No matching transactions found in the last {blocks_to_scan} blocks")
            raise ValueError(f"No recent transactions found for address {address}")
            
        except Exception as e:
            logger.error(f"Error getting transaction details: {str(e)}")
            raise 

    def get_raw_transaction_info(self, txid):
        """Get detailed transaction information"""
        if not self.is_available:
            logger.warning("Bitcoin Core RPC not available, skipping transaction info")
            return {}
            
        try:
            # First get the raw transaction
            raw_tx = self._call_rpc("getrawtransaction", [txid, True])
            
            # Extract relevant information
            block_hash = raw_tx.get('blockhash')
            block_time = None
            block_number = None
            
            if block_hash:
                # Get block information
                block_info = self._call_rpc("getblock", [block_hash])
                block_time = datetime.fromtimestamp(block_info.get('time', 0))
                block_number = block_info.get('height')
            
            return {
                'txid': txid,
                'block_hash': block_hash,
                'block_time': block_time,
                'block_number': block_number,
                'confirmations': raw_tx.get('confirmations', 0),
                'time': raw_tx.get('time'),
                'size': raw_tx.get('size'),
                'vsize': raw_tx.get('vsize'),
                'version': raw_tx.get('version'),
                'vin': raw_tx.get('vin', []),
                'vout': raw_tx.get('vout', [])
            }
        except Exception as e:
            logger.error(f"Error getting transaction info for {txid}: {e}")
            return {}
    
    def update_transaction_block_info(self, transaction):
        """Update block information for a transaction"""
        if not self.is_available:
            logger.warning("Bitcoin Core RPC not available, skipping block info update")
            return False
            
        if not transaction.operation_hash:
            return False
        
        try:
            tx_info = self.get_raw_transaction_info(transaction.operation_hash)
            
            if tx_info.get('block_number') and tx_info.get('block_time'):
                transaction.block_number = tx_info['block_number']
                transaction.block_time = tx_info['block_time']
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error updating block info: {e}")
            return False

    def import_address(self, address):
        """Import an address into the watch-only wallet"""
        logger.debug(f"Importing address to watch list: {address}")
        
        try:
            # Simple importaddress call
            self._call_rpc("importaddress", [address, "", False])
            logger.debug("Successfully imported address")
        except Exception as e:
            if "already have key" in str(e):
                logger.debug("Address already being watched")
            else:
                raise 

    def check_address_utxos(self, address, start_block=None):
        """Check UTXOs for an address using listunspent"""
        if not self.is_available:
            logger.warning("Bitcoin Core RPC not available, skipping UTXO check")
            return [], Decimal('0')
            
        logger.debug(f"Getting UTXOs for address: {address}")
        
        try:
            # First try to load the watch wallet (in case it's not loaded)
            try:
                self.load_watch_wallet()
            except Exception as e:
                if "is already loaded" not in str(e):
                    logger.warning(f"Could not load watch wallet: {e}")
            
            # Use listunspent with address filter - much faster than scantxoutset
            utxos = self._call_rpc("listunspent", [0, 9999999, [address]])
            
            if utxos:
                total_amount = Decimal(str(sum(utxo.get('amount', 0) for utxo in utxos)))
                logger.debug(f"Found {len(utxos)} UTXOs with total amount: {total_amount} BTC")
                return utxos, total_amount
            else:
                logger.debug("No UTXOs found for address")
                return [], Decimal('0')
            
        except Exception as e:
            logger.error(f"Error getting UTXOs: {e}")
            # If listunspent fails (e.g., address not in wallet), fall back to scantxoutset
            logger.info("Falling back to scantxoutset (this may be slow)")
            return self._fallback_check_address_utxos(address)
    
    def _fallback_check_address_utxos(self, address):
        """Fallback UTXO check using scantxoutset for addresses not in wallet"""
        logger.debug(f"Scanning UTXOs for address: {address} (fallback method)")
        
        try:
            # First check if there's a scan in progress
            try:
                status = self._call_rpc("scantxoutset", ["status"])
                if status.get('progress', 0) > 0:
                    logger.info("Aborting existing UTXO scan")
                    self._call_rpc("scantxoutset", ["abort"])
            except Exception as e:
                logger.debug(f"No existing scan or error checking status: {e}")
            
            # Use scantxoutset to find current UTXOs
            scan_result = self._call_rpc("scantxoutset", ["start", [f"addr({address})"]])
            
            if scan_result.get('success'):
                total_amount = Decimal(str(scan_result.get('total_amount', 0)))
                utxos = scan_result.get('unspents', [])
                logger.debug(f"Found {len(utxos)} UTXOs with total amount: {total_amount} BTC")
                return utxos, total_amount
            else:
                logger.error("UTXO scan failed")
                return [], Decimal('0')
            
        except Exception as e:
            logger.error(f"Error scanning UTXOs: {e}")
            return [], Decimal('0') 