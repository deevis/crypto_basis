import os
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta
import json
import logging
from decimal import Decimal
import urllib.parse

# Configure logging with timestamp and level
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class AddressNotFoundInTransactionError(Exception):
    """Exception raised when an address is not found in a transaction's outputs"""
    def __init__(self, message, tx_data=None, address=None):
        super().__init__(message)
        self.tx_data = tx_data
        self.address = address

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
                        # Raise exception with transaction data - let caller handle UI
                        raise AddressNotFoundInTransactionError(
                            f"Address {address} not found in transaction outputs",
                            tx_data=tx,
                            address=address
                        )
                    
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
    
    # ========================================================================
    # UTXO History Tracing Methods
    # ========================================================================
    
    # Exchange detection thresholds
    EXCHANGE_INPUT_THRESHOLD = 20   # Transactions with > 20 inputs likely from exchange
    EXCHANGE_OUTPUT_THRESHOLD = 20  # Transactions with > 20 outputs likely from exchange (lowered from 50)
    EXCHANGE_COMBINED_THRESHOLD = 25  # Or combined inputs + outputs > 25 (lowered from 30)
    EXCHANGE_WITHDRAWAL_OUTPUT_MIN = 10  # Min outputs for withdrawal pattern detection
    EXCHANGE_WITHDRAWAL_RATIO = 5  # Output/input ratio > 5 suggests exchange withdrawal
    
    def is_coinbase_transaction(self, tx_data):
        """
        Check if a transaction is a coinbase (mining reward) transaction.
        Coinbase transactions have a single input with 'coinbase' field instead of 'txid'.
        """
        vin = tx_data.get('vin', [])
        if len(vin) == 1 and 'coinbase' in vin[0]:
            return True
        return False
    
    def detect_exchange_indicators(self, tx_data):
        """
        Detect if a transaction looks like it came from an exchange.
        Returns a dict with indicators and whether it's likely an exchange.
        
        Exchange-like patterns:
        - Many inputs (consolidation or payout batching)
        - Many outputs (batch payouts)
        - Specific known exchange address patterns
        """
        indicators = {}
        is_exchange_like = False
        
        vin = tx_data.get('vin', [])
        vout = tx_data.get('vout', [])
        
        input_count = len(vin)
        output_count = len(vout)
        
        indicators['input_count'] = input_count
        indicators['output_count'] = output_count
        
        # Check for high input count (exchange consolidation or batched sends)
        if input_count > self.EXCHANGE_INPUT_THRESHOLD:
            indicators['high_input_count'] = True
            is_exchange_like = True
        
        # Check for high output count (batch payouts)
        if output_count > self.EXCHANGE_OUTPUT_THRESHOLD:
            indicators['high_output_count'] = True
            is_exchange_like = True
        
        # Check combined threshold
        if input_count + output_count > self.EXCHANGE_COMBINED_THRESHOLD:
            indicators['high_combined_count'] = True
            is_exchange_like = True
        
        # Check for exchange WITHDRAWAL pattern: few inputs, many outputs
        # This is a classic pattern: exchange consolidates to hot wallet (1-3 inputs)
        # then batch pays out to many users (many outputs)
        if input_count <= 3 and output_count >= self.EXCHANGE_WITHDRAWAL_OUTPUT_MIN:
            # Calculate output/input ratio
            ratio = output_count / max(input_count, 1)
            if ratio >= self.EXCHANGE_WITHDRAWAL_RATIO:
                indicators['exchange_withdrawal_pattern'] = True
                indicators['output_input_ratio'] = ratio
                is_exchange_like = True
                logger.info(f"Detected exchange withdrawal pattern: {input_count} inputs, {output_count} outputs (ratio: {ratio:.1f})")
        
        # Calculate total input and output values
        total_output = sum(v.get('value', 0) for v in vout)
        indicators['total_output_btc'] = total_output
        
        # Very large transactions are often exchange-related
        if total_output > 100:  # > 100 BTC
            indicators['large_value'] = True
            # Don't set is_exchange_like just for this, but note it
        
        return is_exchange_like, indicators
    
    def get_output_address(self, vout_data):
        """Extract address from a transaction output"""
        script_pub_key = vout_data.get('scriptPubKey', {})
        
        # New format (single address)
        if 'address' in script_pub_key:
            return script_pub_key['address']
        # Old format (multiple addresses)
        elif 'addresses' in script_pub_key:
            addresses = script_pub_key['addresses']
            return addresses[0] if addresses else None
        
        return None
    
    def trace_utxo_backwards(self, txid, vout, max_hops=10, max_transactions=100,
                              current_hop=0, visited=None, transaction_count=None):
        """
        Trace a UTXO backwards through the blockchain to find its origin.
        
        Args:
            txid: Transaction ID containing the output
            vout: Output index in the transaction
            max_hops: Maximum depth to trace back per branch
            max_transactions: Maximum TOTAL transactions to explore (prevents exponential explosion)
            current_hop: Current hop number (for recursion)
            visited: Set of already visited txid:vout pairs (shared across all branches)
            transaction_count: Mutable list [count] to track total transactions across recursive calls
        
        Returns:
            List of trace entries, each containing:
            - hop_number: Which hop this is
            - txid: Transaction ID
            - vout: Output index
            - amount: Amount in BTC
            - block_height: Block number
            - block_time: Block timestamp
            - source_address: Address that received this output
            - input_count: Number of inputs in transaction
            - output_count: Number of outputs in transaction
            - is_coinbase: Whether this is a coinbase transaction
            - is_exchange_like: Whether this looks like an exchange transaction
            - exchange_indicators: Dict of exchange detection indicators
            - termination_reason: Why tracing stopped (if applicable)
        """
        if visited is None:
            visited = set()
        if transaction_count is None:
            transaction_count = [0]  # Mutable container to share count across recursive calls
        
        # Check global transaction limit FIRST
        if transaction_count[0] >= max_transactions:
            logger.warning(f"Reached max transaction limit ({max_transactions}), stopping trace")
            return [{
                'hop_number': current_hop,
                'txid': txid,
                'vout': vout,
                'amount': Decimal('0'),
                'termination_reason': 'MAX_TRANSACTIONS',
                'error': f'Reached limit of {max_transactions} transactions'
            }]
        
        # Avoid infinite loops - shared visited set across all branches
        utxo_key = f"{txid}:{vout}"
        if utxo_key in visited:
            logger.debug(f"Already visited {utxo_key}, skipping")
            return []
        visited.add(utxo_key)
        
        # Increment global transaction count
        transaction_count[0] += 1
        
        if transaction_count[0] % 10 == 0:
            logger.info(f"Explored {transaction_count[0]} transactions so far...")
        
        logger.debug(f"Tracing UTXO {utxo_key} at hop {current_hop}")
        
        try:
            # Get the transaction
            tx_data = self._call_rpc("getrawtransaction", [txid, True])
            
            if not tx_data:
                logger.error(f"Could not get transaction {txid}")
                return [{
                    'hop_number': current_hop,
                    'txid': txid,
                    'vout': vout,
                    'amount': Decimal('0'),
                    'termination_reason': 'ERROR',
                    'error': 'Transaction not found'
                }]
            
            # Get block info
            block_height = None
            block_time = None
            if 'blockhash' in tx_data:
                try:
                    block_info = self._call_rpc("getblock", [tx_data['blockhash']])
                    block_height = block_info.get('height')
                    block_time = datetime.fromtimestamp(block_info.get('time', 0))
                except Exception as e:
                    logger.warning(f"Could not get block info: {e}")
            
            # Get the specific output
            vouts = tx_data.get('vout', [])
            if vout >= len(vouts):
                logger.error(f"Output index {vout} out of range for tx {txid}")
                return [{
                    'hop_number': current_hop,
                    'txid': txid,
                    'vout': vout,
                    'amount': Decimal('0'),
                    'termination_reason': 'ERROR',
                    'error': f'Output index {vout} out of range'
                }]
            
            output_data = vouts[vout]
            amount = Decimal(str(output_data.get('value', 0)))
            source_address = self.get_output_address(output_data)
            
            # Check if coinbase
            is_coinbase = self.is_coinbase_transaction(tx_data)
            
            # Check for exchange-like patterns
            is_exchange_like, exchange_indicators = self.detect_exchange_indicators(tx_data)
            
            input_count = len(tx_data.get('vin', []))
            output_count = len(tx_data.get('vout', []))
            
            # Build current hop entry
            entry = {
                'hop_number': current_hop,
                'txid': txid,
                'vout': vout,
                'amount': amount,
                'block_height': block_height,
                'block_time': block_time,
                'source_address': source_address,
                'input_count': input_count,
                'output_count': output_count,
                'is_coinbase': is_coinbase,
                'is_exchange_like': is_exchange_like,
                'exchange_indicators': exchange_indicators,
                'termination_reason': None
            }
            
            # Check termination conditions
            if is_coinbase:
                entry['termination_reason'] = 'COINBASE'
                logger.info(f"Reached coinbase transaction at hop {current_hop}: {txid}")
                return [entry]
            
            if is_exchange_like:
                entry['termination_reason'] = 'EXCHANGE'
                logger.info(f"Reached exchange-like transaction at hop {current_hop}: {txid}")
                logger.info(f"  Indicators: {exchange_indicators}")
                return [entry]
            
            if current_hop >= max_hops:
                entry['termination_reason'] = 'MAX_HOPS'
                logger.info(f"Reached max hops ({max_hops}) at {txid}")
                return [entry]
            
            # Continue tracing - follow each input
            results = [entry]
            
            vin = tx_data.get('vin', [])
            for vin_index, inp in enumerate(vin):
                # Check if we've hit the transaction limit before processing more inputs
                if transaction_count[0] >= max_transactions:
                    logger.info(f"Stopping input exploration - reached transaction limit")
                    break
                
                # Get the previous transaction output that this input spends
                prev_txid = inp.get('txid')
                prev_vout = inp.get('vout')
                
                if prev_txid is None or prev_vout is None:
                    # This shouldn't happen for non-coinbase, but handle it
                    logger.warning(f"Input missing txid/vout: {inp}")
                    continue
                
                # Recursively trace - SHARE visited set and transaction_count across all branches
                sub_results = self.trace_utxo_backwards(
                    prev_txid, prev_vout, 
                    max_hops=max_hops,
                    max_transactions=max_transactions,
                    current_hop=current_hop + 1,
                    visited=visited,  # Shared across all branches
                    transaction_count=transaction_count  # Shared counter
                )
                
                # Add flow information to link this transaction to the previous one
                for sub_entry in sub_results:
                    if sub_entry.get('hop_number') == current_hop + 1:
                        # This is the immediate child - add flow info
                        sub_entry['spent_by_txid'] = txid
                        sub_entry['spent_by_vin'] = vin_index
                
                results.extend(sub_results)
            
            return results
            
        except Exception as e:
            logger.error(f"Error tracing UTXO {txid}:{vout}: {e}")
            return [{
                'hop_number': current_hop,
                'txid': txid,
                'vout': vout,
                'amount': Decimal('0'),
                'termination_reason': 'ERROR',
                'error': str(e)
            }]
    
    def trace_address_utxos(self, address, max_hops=10, max_transactions=100):
        """
        Trace all UTXOs for an address backwards to their origins.
        
        Args:
            address: Bitcoin address to trace
            max_hops: Maximum depth per trace branch
            max_transactions: Maximum total transactions to explore per UTXO
        
        Returns:
            Dict mapping utxo_key (txid:vout) to list of trace entries
        """
        logger.info(f"Tracing UTXOs for address: {address}")
        
        # Get current UTXOs for the address
        utxos, total = self.check_address_utxos(address)
        
        if not utxos:
            logger.info(f"No UTXOs found for address {address}")
            return {}
        
        logger.info(f"Found {len(utxos)} UTXOs totaling {total} BTC")
        
        results = {}
        for utxo in utxos:
            txid = utxo.get('txid')
            vout = utxo.get('vout')
            utxo_key = f"{txid}:{vout}"
            
            logger.info(f"Tracing UTXO {utxo_key}...")
            trace = self.trace_utxo_backwards(txid, vout, max_hops=max_hops, max_transactions=max_transactions)
            results[utxo_key] = trace
        
        return results 