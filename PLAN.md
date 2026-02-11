# Cointools: Top Holder Behavior Tracker — Project Plan

## Objective

Build a CLI tool that tracks the top holders of on-chain tokens and analyzes
whether large holders are accumulating (buying) or distributing (selling) over
configurable time periods.

---

## Tech Stack

| Component        | Choice               | Rationale                                       |
|------------------|----------------------|-------------------------------------------------|
| Language         | Python 3.11+         | Fast prototyping, excellent HTTP/data libraries  |
| Data Storage     | SQLite               | Zero-config local DB, perfect for time-series snapshots |
| CLI Framework    | `click`              | Clean subcommand structure, argument parsing     |
| Display          | `rich`               | Color-coded tables, progress bars in terminal    |
| HTTP             | `httpx`              | Modern async-capable HTTP client                 |
| Chain            | Solana (initial)     | Free RPC access, `getTokenLargestAccounts` returns top 20 holders natively |

### Why Solana-first?

Solana's native RPC method `getTokenLargestAccounts` returns the top 20 holders
for any SPL token in a single free call — no API key required. This means the
tool works out of the box with zero configuration. EVM chain support can be
added later via Moralis/Etherscan APIs.

---

## Architecture

```
cointools/
├── pyproject.toml           # Project metadata, dependencies, entry point
├── README.md                # (will not be created unless requested)
├── src/
│   └── cointools/
│       ├── __init__.py
│       ├── cli.py           # Click CLI: subcommands (track, snapshot, report, watch, list)
│       ├── config.py        # RPC endpoints, defaults, user config
│       ├── db.py            # SQLite schema, connection, queries
│       ├── chains/
│       │   ├── __init__.py
│       │   └── solana.py    # Solana RPC client (getTokenLargestAccounts, token metadata)
│       ├── tracker.py       # Core logic: take snapshots, diff balances
│       └── display.py       # Rich tables, formatting, color-coded output
└── tests/
    ├── __init__.py
    ├── test_db.py
    ├── test_tracker.py
    └── test_solana.py
```

---

## Data Model (SQLite)

### `tokens`
| Column       | Type    | Description                          |
|-------------|---------|--------------------------------------|
| mint_address | TEXT PK | Token mint address                   |
| chain        | TEXT    | "solana" (extensible later)          |
| symbol       | TEXT    | Token symbol (if resolvable)         |
| name         | TEXT    | Token name (if resolvable)           |
| decimals     | INTEGER | Token decimal places                 |
| created_at   | TEXT    | ISO timestamp of first tracking      |

### `snapshots`
| Column       | Type        | Description                    |
|-------------|-------------|--------------------------------|
| id           | INTEGER PK  | Auto-increment                 |
| mint_address | TEXT FK     | References tokens              |
| taken_at     | TEXT        | ISO timestamp                  |

### `holder_balances`
| Column          | Type       | Description                     |
|----------------|------------|---------------------------------|
| id              | INTEGER PK | Auto-increment                 |
| snapshot_id     | INTEGER FK | References snapshots            |
| holder_address  | TEXT       | Wallet/token-account address    |
| owner_address   | TEXT       | Owner wallet (resolved)         |
| balance         | REAL       | Human-readable balance (with decimals applied) |
| rank            | INTEGER    | Position in top holders (1-20)  |

---

## CLI Commands

### `cointools track <mint_address>`
Register a token and take the first snapshot of its top 20 holders.

```
$ cointools track 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr
Tracking token: POPCAT (7GCihgDB...)
Snapshot #1 taken — 20 holders recorded.
```

### `cointools snapshot <mint_address>`
Take a new snapshot for an already-tracked token. Compares to previous snapshot
and shows a quick summary of changes.

```
$ cointools snapshot 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr
Snapshot #5 taken for POPCAT
  ↑ 12 holders increased position
  ↓ 6 holders decreased position
  → 2 holders unchanged
```

### `cointools report <mint_address> [--period 24h|7d|30d|all]`
Show a detailed table comparing current holder balances vs. a previous point in
time. Defaults to comparing against the most recent prior snapshot.

```
$ cointools report 7GCihgDB... --period 7d

  POPCAT Top Holder Report (7d change)
  ─────────────────────────────────────────────────────
  Rank │ Holder       │ Balance       │ Change      │ Signal
  ─────┼──────────────┼───────────────┼─────────────┼────────
   1   │ 4xK9..2nF   │ 15,230,000   │ +2,100,000  │ 🟢 BUY
   2   │ 8mR3..7qP   │ 12,800,000   │ -500,000    │ 🔴 SELL
   3   │ 2vJ5..9kL   │ 10,450,000   │ 0           │ ⚪ HOLD
  ...
  ─────────────────────────────────────────────────────
  Summary: 14 buying │ 4 selling │ 2 holding
  Net sentiment: ACCUMULATION
```

### `cointools watch <mint_address> [--interval 60]`
Continuously poll and snapshot at a given interval (seconds). Prints a live
updating summary after each poll.

### `cointools list`
Show all tracked tokens with their last snapshot time and holder count.

### `cointools remove <mint_address>`
Stop tracking a token and delete its data.

---

## Core Analysis Logic

1. **Snapshot diffing**: Compare holder balances between two snapshots. Match
   holders by `owner_address` (not token-account address, since those can change).
2. **Signal classification**:
   - Balance increased → **BUY** (green)
   - Balance decreased → **SELL** (red)
   - Balance unchanged → **HOLD** (neutral)
   - New in top 20 → **NEW** (blue)
   - Dropped from top 20 → **EXIT** (yellow)
3. **Aggregate sentiment**: Count buyers vs sellers among top holders. Classify
   overall as ACCUMULATION, DISTRIBUTION, or NEUTRAL.
4. **Period selection**: `--period` flag finds the closest snapshot to the
   requested time window (24h, 7d, 30d) and diffs against it.

---

## Configuration & RPC

- Default Solana RPC: `https://api.mainnet-beta.solana.com` (free, rate-limited)
- Users can set a custom RPC (e.g., Helius) via `cointools config set rpc_url <url>`
- Config stored in `~/.cointools/config.json`
- Database stored in `~/.cointools/cointools.db`

---

## Build Steps (implementation order)

1. **Project scaffolding** — `pyproject.toml`, package structure, dependencies
2. **Database layer** — Schema creation, insert/query functions
3. **Solana RPC client** — `getTokenLargestAccounts`, token metadata resolution
4. **Tracker core** — Snapshot taking, diffing, signal classification
5. **Display layer** — Rich tables, color coding, summary formatting
6. **CLI wiring** — Click commands connecting everything together
7. **Watch mode** — Polling loop with live output
8. **Tests** — Unit tests for DB, tracker logic, and Solana client mocking
9. **Config management** — User-configurable RPC endpoint

---

## Scope Boundaries

### In scope
- Solana SPL token top-20 holder tracking
- Local SQLite storage of balance snapshots over time
- CLI-based reporting with buy/sell/hold signals
- Configurable time period comparisons
- Continuous watch mode

### Out of scope (future additions)
- EVM chain support (Ethereum, Base, etc.)
- Web dashboard / GUI
- Push notifications or alerts
- On-chain transaction parsing (we track balance deltas, not individual txns)
- Automated trading signals or recommendations
