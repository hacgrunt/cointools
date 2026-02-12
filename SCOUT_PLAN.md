# Scout: Smart Money Token Discovery

## Problem

You hear about coins too late. By the time someone posts in a chat, the
edge is gone. Social signal lags on-chain signal by hours or days.

## Solution

Track what the best on-chain traders are buying. When multiple tracked
wallets converge on the same token, that's signal. Surface it before
anyone posts about it.

## Why not just PNL leaderboards?

PNL as a wallet quality metric is broken:
- Selling wallets split across addresses → understated PNL
- Sybil/airdrop farmers show huge "PNL" on worthless tokens
- Sandwich bots and arb bots have great PNL but meaningless buys
- PNL is backward-looking — last month's winner is this month's bagholder

The right metric is **consistent early entry with held upside**: wallets
that buy tokens at low mcap and multiple of them go on to do well. That's
Phase 2. Phase 1 starts with manually curated wallets you already trust.

## Architecture

```
You add wallets ──► Scout scans their swaps (Helius API)
                         │
                         ▼
                   Parse buys/sells
                   Filter noise (dust, stables, LPs)
                         │
                         ▼
                   Aggregate by token
                   "Token X: 4 wallets bought in last 6h"
                         │
                         ▼
                   Fetch metadata (DexScreener)
                   Price, mcap, liquidity, volume
                         │
                         ▼
                   Rank by conviction
                   # unique buyers × SOL volume × recency
                         │
                         ▼
                   Display feed (CLI + Web)
```

## Phases

### Phase 1: MVP — Manual Wallet Tracking + Token Feed (NOW)

**What**: Given a set of manually-added wallets, show what tokens they're
buying right now, ranked by how many wallets are converging.

**Components**:
- Wallet management: add/remove/list tracked wallets with labels
- Transaction scanner: Helius Enhanced Transactions API (SWAP filter)
- Swap parser: determine BUY vs SELL, token mint, SOL amount
- Filters: skip stablecoins, wrapped SOL, dust trades (<0.01 SOL)
- Aggregator: group by token, count unique buyers, sum SOL flow
- Token metadata: DexScreener API (price, mcap, liquidity)
- Ranking: conviction score = unique_buyers × 10 + SOL_volume + net_flow_bonus
- CLI: `cointools scout add/remove/list/scan`
- Web dashboard: `web/scout.html`

**APIs required**:
- Helius Enhanced Transactions (free tier, needs API key)
- DexScreener (free, no auth)

### Phase 2: Smart Filtering + Wallet Discovery

**What**: Automatically find good wallets and score them.

- Walk backward from tokens that did 10x+: who bought in first 24h?
- Wallet scoring: early entry rate, win rate, hold duration, avg multiple
- Enhanced bot detection: same-block buy+sell ratio, tx frequency
- Exchange wallet detection: volume patterns, unique token count
- Wallet quality tiers: S/A/B/C based on composite score
- Auto-refresh wallet scores on a schedule

### Phase 3: Real-time Dashboard + Alerts

**What**: Live view of the token landscape with alerting.

- Polling/webhook monitoring for new wallet activity
- Dashboard views: Trending, Early, Consensus, Exits
- Alert system: "3 tracked wallets just bought TOKEN in 2h"
- Historical tracking: did surfaced tokens actually perform?
- Conviction decay: signals weaken if wallets start selling

## Technical Design (Phase 1)

### Data flow

```
cointools scout scan --period 24h
  │
  ├─ Load wallets from SQLite
  ├─ For each wallet:
  │    └─ GET helius/v0/addresses/{addr}/transactions?type=SWAP
  │       └─ Paginate until timestamp < period_start
  ├─ Parse each SWAP transaction:
  │    ├─ events.swap.nativeInput → SOL spent
  │    ├─ events.swap.tokenOutputs → tokens received (BUY)
  │    ├─ events.swap.tokenInputs → tokens sent (SELL)
  │    └─ Skip if base_token or dust
  ├─ Upsert trades into SQLite (dedupe by signature)
  ├─ Aggregate: GROUP BY token_mint, count unique buyers
  ├─ Fetch metadata from DexScreener (batched, 30/request)
  ├─ Filter: skip tokens with liquidity < $1K
  ├─ Rank by conviction score
  └─ Display ranked feed
```

### Database tables

```sql
scout_wallets (address PK, label, added_at, last_scanned, is_active)
scout_trades  (id PK, wallet_address FK, signature UNIQUE, timestamp,
               trade_type, token_mint, token_amount, sol_amount, source)
```

### Filtering strategy

**Base tokens excluded**: USDC, USDT, Wrapped SOL
**Dust threshold**: < 0.01 SOL (~$1-2)
**Liquidity floor**: < $1K USD on DexScreener
**Known programs**: System, Token, Jupiter, Raydium, Orca, etc.
**Exchange wallets**: Binance, Coinbase, Kraken hot wallets

### Module structure

```
src/cointools/scout/
├── __init__.py      # Package exports
├── db.py            # SQLite: wallet CRUD, trade storage, aggregation
├── filters.py       # Constants: stablecoins, programs, thresholds
├── scanner.py       # Helius API: fetch + parse swap transactions
├── tokens.py        # DexScreener API: token metadata
├── aggregator.py    # Build ranked token feed from aggregated data
└── display.py       # Rich terminal output for CLI
```

### CLI commands

```bash
cointools scout add <address> [--label name]   # Track a wallet
cointools scout remove <address>                # Stop tracking
cointools scout list                            # Show tracked wallets
cointools scout scan [--period 24h]             # Scan and display feed
```
