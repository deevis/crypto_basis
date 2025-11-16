# OP_RETURN Fee Tracking - Summary

## What We're Now Tracking

For each large OP_RETURN transaction (>83 bytes), we now capture:

### Transaction Costs
1. **Transaction Fee** - Total satoshis paid for the entire transaction
2. **Transaction Size** - Size in vbytes (virtual bytes, SegWit-compatible)
3. **Fee Rate** - Satoshis per vbyte (sats/vbyte)
4. **Cost per Byte of OP_RETURN Data** - How much each byte of the embedded data cost
5. **Input/Output Counts** - Number of transaction inputs and outputs

### Where This Data is Stored

1. **Database** (`large_op_returns` table):
   - `tx_fee` (INT) - Total fee in satoshis
   - `tx_size` (INT) - Transaction size in vbytes
   - `fee_rate` (FLOAT) - Fee rate in sats/vbyte
   - `cost_per_byte` (FLOAT) - Cost per byte of OP_RETURN data
   - `tx_input_count` (INT) - Number of inputs
   - `tx_output_count` (INT) - Number of outputs

2. **Metadata JSON files**:
   - `transaction_fee_sats`
   - `transaction_size_vbytes`
   - `fee_rate_sats_per_vbyte`
   - `cost_per_byte_of_data`
   - `tx_inputs`
   - `tx_outputs`

### Example Output

When scanning blocks, you'll now see:
```
📦 Found OP_RETURN in block 922071, tx 9070fb51..., vout 0
  Size: 911 bytes
  Fee: 113,500 sats (100.09 sats/vbyte)
  Cost: 124.59 sats/byte of OP_RETURN data
```

When querying:
```
[FEES] Transaction Fee Statistics:
   Transactions with fee data: 1
   Total fees paid:            113,500 sats (0.00113500 BTC)
   Average fee:                113,500 sats
   Average fee rate:           100.09 sats/vbyte
   Fee rate range:             100.09 - 100.09 sats/vbyte
   Avg cost per byte of data:  124.59 sats/byte
```

## Re-Scanning Existing Blocks

**Important:** Only newly scanned blocks will have fee data. To add fee information to your existing 150 OP_RETURNs, you have two options:

### Option 1: Re-scan specific blocks
```bash
python reset_block.py <block_number>
python op_return_scanner.py <block_number> <block_number>
```

### Option 2: Re-scan all blocks with OP_RETURNs
You could create a script to:
1. Query all blocks with `large_op_returns_found > 0`
2. Delete and re-scan each one
3. This will populate fee data for all historical OP_RETURNs

### Option 3: Continue scanning new blocks
As you scan forward (--continue) or backward (--backwards), new scans will automatically include fee data.

## Technical Details

### How Fee is Calculated

From Bitcoin Core RPC with verbosity 2 (`getblock` with 2):
- The 'fee' field is directly available for each transaction
- Fee = Sum of inputs - Sum of outputs (but we use the provided 'fee' field)
- Converts from BTC to satoshis (multiply by 100,000,000)

### Formula
```
fee_rate = tx_fee / tx_size (vbytes)
cost_per_byte = tx_fee / data_size (OP_RETURN bytes)
```

## Additional Data We Could Capture

While the scanner is running, we could also capture:

1. **Block difficulty** - Mining difficulty at block height
2. **Block reward** - Coinbase transaction amount
3. **Confirmations** - How many confirmations the block has
4. **Transaction version** - Could indicate special transaction types
5. **Lock time** - Transaction lock time
6. **SegWit flag** - Whether transaction uses SegWit
7. **RBF flag** - Whether transaction is replaceable (Replace-By-Fee)

Let me know if you'd like any of these added!

## Dashboard Integration

The fee data is **not yet** displayed in the HTML dashboard. Would you like me to add:
- Fee statistics charts
- Fee rate over time
- Cost per byte trends
- Most expensive OP_RETURNs ranking

