# Monitor Sets

This directory contains scripts for managing and monitoring sets of Bitcoin addresses of interest.

## Files

### Address Sets
- `addresses_of_interest.json` - Contains notable Bitcoin addresses (governments, institutions, etc.)
- Any other `.json` files - Additional address sets you want to monitor

### Scripts
- `sync.py` - Syncs address sets to Bitcoin Core watch-only wallets
- `check_activity.py` - Monitors addresses for new activity and saves detailed data

## JSON Format

Each monitor set JSON file should contain an array of address objects:

```json
[
    {
        "address": "32ixEdVJWo3kmvJGMTZq5jAQVZZeuwnqzo",
        "owner": "El Salvador", 
        "details": "Description of the address",
        "origin_block": 700000
    }
]
```

### Fields
- `address` (required) - The Bitcoin address to monitor
- `owner` (optional) - Who owns/controls this address
- `details` (optional) - Additional information about the address
- `origin_block` (optional) - Block number to start scanning from (for efficiency)

## Usage

### 1. Sync Addresses to Bitcoin Core

First, make sure your addresses are imported as watch-only wallets:

```bash
cd monitor_sets
python sync.py
```

This will:
- Create a watch-only wallet for each JSON file (e.g., `crypto-basis-addresses_of_interest`)
- Import all addresses from the JSON file into the corresponding wallet
- Use `importmulti` with origin block timestamps for efficient rescanning
- Skip addresses that are already imported

### 2. Check for Activity

Monitor all addresses for new transactions:

```bash
python check_activity.py
```

This will:
- Scan all addresses across all monitor sets
- Detect new transactions since the last check
- Save activity data to `{set_name}/{address}.json` files

## Activity Data Format

Each address's activity is saved to `{set_name}/{address}.json`:

```json
[
    {
        "txid": "abc123...",
        "block_number": 800000,
        "date": "2023-01-01T12:00:00",
        "amount": 1.5,
        "balance_after": 10.5,
        "current_balance": 10.5,
        "confirmations": 6,
        "utxos": [
            {
                "txid": "abc123...",
                "vout": 0,
                "amount": 1.5,
                "confirmations": 6,
                "spendable": false,
                "safe": true
            }
        ],
        "last_updated": "2023-01-01T12:05:00"
    }
]
```

## Directory Structure

After running the scripts, your directory will look like:

```
monitor_sets/
├── addresses_of_interest.json
├── sync.py
├── check_activity.py
├── README.md
└── addresses_of_interest/
    ├── 32ixEdVJWo3kmvJGMTZq5jAQVZZeuwnqzo.json
    ├── bc1qa5wkgaew2dkv56kfvj49j0av5nml45x9ek9hz6.json
    └── ...
```

## Requirements

- Bitcoin Core running with RPC enabled
- Proper environment variables set for BTC RPC connection
- Python dependencies from the main project

## Tips

- Run `sync.py` whenever you add new addresses to JSON files
- Run `check_activity.py` regularly (e.g., via cron) to monitor for new activity
- Use `origin_block` when you know when an address first became active to speed up initial sync
- The sync script handles timeouts gracefully - large rescans continue on the Bitcoin Core node even if the script exits 