"""Helius Enhanced Transactions API scanner for wallet swap activity."""

from __future__ import annotations

import asyncio

import httpx

from cointools.scout.filters import BASE_TOKENS, is_base_token, is_dust_trade

HELIUS_BASE_URL = "https://api.helius.xyz/v0"

# Conservative delay between API calls to stay under free-tier limits.
_API_DELAY = 0.12


def parse_swap_transaction(tx: dict, wallet_address: str) -> list[dict]:
    """Parse a Helius enhanced SWAP transaction into trade dicts.

    Each returned dict has keys:
        wallet_address, signature, timestamp, trade_type (BUY|SELL),
        token_mint, token_amount, sol_amount, source
    """
    swap_event = (tx.get("events") or {}).get("swap")
    if not swap_event:
        return []

    signature = tx.get("signature", "")
    timestamp = tx.get("timestamp", 0)
    source = tx.get("source", "UNKNOWN")

    # --- SOL amount from native transfers ---
    sol_amount = 0.0
    native_in = swap_event.get("nativeInput")
    native_out = swap_event.get("nativeOutput")
    if native_in:
        sol_amount = int(native_in.get("amount", 0)) / 1e9
    elif native_out:
        sol_amount = int(native_out.get("amount", 0)) / 1e9

    # --- First pass: extract stablecoin/base-token value as SOL proxy ---
    stable_amount = 0.0
    for token in swap_event.get("tokenInputs") or []:
        mint = token.get("mint", "")
        if is_base_token(mint):
            raw = token.get("rawTokenAmount") or {}
            decimals = int(raw.get("decimals", 0))
            stable_amount = (
                int(raw.get("tokenAmount", "0")) / (10**decimals) if decimals else 0
            )
    for token in swap_event.get("tokenOutputs") or []:
        mint = token.get("mint", "")
        if is_base_token(mint) and stable_amount == 0.0:
            raw = token.get("rawTokenAmount") or {}
            decimals = int(raw.get("decimals", 0))
            stable_amount = (
                int(raw.get("tokenAmount", "0")) / (10**decimals) if decimals else 0
            )

    effective_sol = sol_amount or stable_amount
    trades: list[dict] = []

    # --- Second pass: create trades for non-base tokens ---
    for token in swap_event.get("tokenInputs") or []:
        mint = token.get("mint", "")
        if is_base_token(mint):
            continue
        raw = token.get("rawTokenAmount") or {}
        decimals = int(raw.get("decimals", 0))
        amount = int(raw.get("tokenAmount", "0")) / (10**decimals) if decimals else 0

        trades.append(
            {
                "wallet_address": wallet_address,
                "signature": signature,
                "timestamp": timestamp,
                "trade_type": "SELL",
                "token_mint": mint,
                "token_amount": amount,
                "sol_amount": effective_sol,
                "source": source,
            }
        )

    for token in swap_event.get("tokenOutputs") or []:
        mint = token.get("mint", "")
        if is_base_token(mint):
            continue
        raw = token.get("rawTokenAmount") or {}
        decimals = int(raw.get("decimals", 0))
        amount = int(raw.get("tokenAmount", "0")) / (10**decimals) if decimals else 0

        trades.append(
            {
                "wallet_address": wallet_address,
                "signature": signature,
                "timestamp": timestamp,
                "trade_type": "BUY",
                "token_mint": mint,
                "token_amount": amount,
                "sol_amount": effective_sol,
                "source": source,
            }
        )

    # Drop dust
    return [t for t in trades if not is_dust_trade(t["sol_amount"])]


async def scan_wallet_transactions(
    client: httpx.AsyncClient,
    api_key: str,
    wallet_address: str,
    since_timestamp: int,
    *,
    max_pages: int = 5,
) -> list[dict]:
    """Fetch and parse SWAP transactions for *wallet_address* since a time.

    Paginates through Helius Enhanced Transactions API until transactions
    are older than *since_timestamp* or *max_pages* pages are exhausted.
    """
    all_trades: list[dict] = []
    before_sig: str | None = None

    for _ in range(max_pages):
        url = f"{HELIUS_BASE_URL}/addresses/{wallet_address}/transactions"
        params: dict[str, str] = {"api-key": api_key, "type": "SWAP"}
        if before_sig:
            params["before"] = before_sig

        await asyncio.sleep(_API_DELAY)
        try:
            resp = await client.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            transactions: list[dict] = resp.json()
        except (httpx.HTTPError, ValueError):
            break

        if not transactions:
            break

        reached_cutoff = False
        for tx in transactions:
            ts = tx.get("timestamp", 0)
            if ts < since_timestamp:
                reached_cutoff = True
                break
            all_trades.extend(parse_swap_transaction(tx, wallet_address))

        if reached_cutoff:
            break

        before_sig = transactions[-1].get("signature")

    return all_trades


async def scan_all_wallets(
    api_key: str,
    wallet_addresses: list[str],
    since_timestamp: int,
    on_progress: callable | None = None,
) -> list[dict]:
    """Scan multiple wallets sequentially (respects rate limits)."""
    all_trades: list[dict] = []

    async with httpx.AsyncClient() as client:
        for i, addr in enumerate(wallet_addresses):
            if on_progress:
                on_progress(
                    f"Scanning wallet {i + 1}/{len(wallet_addresses)}: "
                    f"{addr[:8]}..."
                )

            trades = await scan_wallet_transactions(
                client, api_key, addr, since_timestamp
            )
            all_trades.extend(trades)

    return all_trades
