# Cointools: Top Holder Behavior Tracker

## What it does

On-demand analysis of top token holders on Solana and EVM chains (Base,
Ethereum, Optimism, Arbitrum, Polygon, BSC). Paste a contract address and
instantly see whether large holders are buying or selling.

## Quick start

```bash
pip install -e .

# Just paste a contract address — chain is auto-detected
cointools analyze 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr          # Solana
cointools analyze 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913              # Base (EVM)

# Options
cointools analyze <address> --period 7d          # Look back 7 days
cointools analyze <address> --chain eth           # Force chain
cointools analyze <address> --html report.html    # Export visual report
cointools watch <address> --interval 300          # Auto-refresh every 5 min
cointools config set rpc_url <url> --chain base   # Custom RPC
```

## How it works

### Solana
1. `getTokenLargestAccounts` → current top 20 holders (1 RPC call)
2. For each holder: `getSignaturesForAddress` → find tx near target time
3. `getTransaction` → extract historical balance from postTokenBalances
4. Delta = current - historical → BUY / SELL / HOLD

### EVM (Base, Ethereum, etc.)
1. Ankr `ankr_getTokenHolders` → current top 20 holders (free, no API key)
2. `eth_call` with `balanceOf(holder)` at estimated historical block
3. Delta = current - historical → BUY / SELL / HOLD

### Visualization
`--html report.html` generates a self-contained HTML file with:
- Bar chart of balance changes per holder
- Doughnut chart of aggregate sentiment (buyers vs sellers)
- Full data table

Single file, no build step. Open locally or host on any static host.

## Architecture

```
src/cointools/
├── cli.py           # Click commands: analyze, watch, config
├── config.py        # RPC URLs, chain detection, periods
├── db.py            # SQLite cache
├── tracker.py       # Signal classification, sentiment scoring
├── display.py       # Rich terminal output
├── export.py        # Self-contained HTML report generation
└── chains/
    ├── solana.py    # Solana RPC client
    └── evm.py       # EVM/Ankr client (Base, ETH, etc.)
```
