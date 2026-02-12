"""Filtering constants and heuristics for scout.

Defines which tokens to skip (stablecoins, wrapped SOL), which addresses
are known programs or exchange wallets, and threshold values for dust
filtering and liquidity floors.
"""

# ---------------------------------------------------------------------------
# Base tokens — swaps involving ONLY these are not interesting signal
# ---------------------------------------------------------------------------

STABLECOINS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",   # USDT
}

WRAPPED_SOL = "So11111111111111111111111111111111111111112"

BASE_TOKENS = {WRAPPED_SOL, *STABLECOINS}

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MIN_TRADE_SOL = 0.01       # ~$1-2 — anything below is dust
MIN_LIQUIDITY_USD = 1_000  # tokens below this are too illiquid to surface

# ---------------------------------------------------------------------------
# Known Solana programs — never meaningful as trader wallets
# ---------------------------------------------------------------------------

KNOWN_PROGRAMS = {
    "11111111111111111111111111111111",                  # System Program
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",     # Token Program
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",    # Token-2022
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",    # Associated Token
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",    # Jupiter v6
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB",    # Jupiter v4
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",   # Raydium V4
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",   # Raydium CLMM
    "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS",    # Raydium Route
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",    # Orca Whirlpool
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",    # Meteora DLMM
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB",   # Meteora Pools
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY",    # Phoenix
    "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",     # Serum/OpenBook
    "ComputeBudget111111111111111111111111111111",       # Compute Budget
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",    # Memo
    "Memo1UhkJBfCR2FcZyiY5GW6TUpXK6gVtoEJBGrP3PU4",   # Memo V1
    "Vote111111111111111111111111111111111111111",       # Vote Program
    "Stake11111111111111111111111111111111111111",       # Stake Program
}

# ---------------------------------------------------------------------------
# Known exchange hot wallets — trades involving these are CEX flow, not alpha
# ---------------------------------------------------------------------------

EXCHANGE_WALLETS = {
    # Binance
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
    "2ojv9BAiHUrvsm9gxDe7fJSzbNZSJcxZvf8dqmWGHG8S",
    # Coinbase
    "H8sMJSCQxfKbeimQVBMeWJHjBJa5C1gJQsCkBRpN6WrJ",
    "GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKTh21yxdRPqn7npE",
    # Kraken
    "4LoauFaEFJikcv8ia2WWieQA15Q9u4xHCr1YGrRkCC4d",
    # Bybit
    "Cguso7YAqAPv6K1BEPh4TFfNjMqeNiPjJLvVbXZqQj8R",
    "AC5RDfQFmDS1deWZos921JfqscXdByf6BKHs5ACWjtW2",
}


def is_base_token(mint: str) -> bool:
    """True if the mint is SOL, WSOL, or a stablecoin."""
    return mint in BASE_TOKENS


def is_dust_trade(sol_amount: float) -> bool:
    """True if the trade is below the dust threshold."""
    return abs(sol_amount) < MIN_TRADE_SOL


def is_known_program(address: str) -> bool:
    return address in KNOWN_PROGRAMS


def is_exchange_wallet(address: str) -> bool:
    return address in EXCHANGE_WALLETS
