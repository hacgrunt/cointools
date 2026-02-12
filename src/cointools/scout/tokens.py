"""DexScreener API client for token metadata."""

from __future__ import annotations

import asyncio

import httpx

DEXSCREENER_BASE = "https://api.dexscreener.com/latest/dex/tokens"

_BATCH_SIZE = 30  # DexScreener max addresses per request
_API_DELAY = 0.3


def _pick_best_pair(pairs: list[dict]) -> dict | None:
    """Select the highest-liquidity Solana pair."""
    solana_pairs = [p for p in pairs if p.get("chainId") == "solana"]
    candidates = solana_pairs or pairs
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda p: float((p.get("liquidity") or {}).get("usd", 0) or 0),
    )


def _parse_pair(pair: dict) -> dict:
    base = pair.get("baseToken") or {}
    liq = pair.get("liquidity") or {}
    vol = pair.get("volume") or {}
    return {
        "mint": base.get("address", ""),
        "name": base.get("name", "Unknown"),
        "symbol": base.get("symbol", "???"),
        "price_usd": float(pair.get("priceUsd") or 0),
        "market_cap": float(pair.get("marketCap") or pair.get("fdv") or 0),
        "liquidity_usd": float(liq.get("usd") or 0),
        "volume_24h": float(vol.get("h24") or 0),
        "pair_url": pair.get("url", ""),
        "dex": pair.get("dexId", ""),
    }


async def fetch_token_metadata(
    client: httpx.AsyncClient, mint_addresses: list[str]
) -> dict[str, dict]:
    """Fetch metadata for tokens from DexScreener.

    Returns mapping of mint address → metadata dict.
    Batches requests to stay within API limits.
    """
    result: dict[str, dict] = {}

    for i in range(0, len(mint_addresses), _BATCH_SIZE):
        batch = mint_addresses[i : i + _BATCH_SIZE]
        addr_str = ",".join(batch)

        if i > 0:
            await asyncio.sleep(_API_DELAY)

        try:
            resp = await client.get(
                f"{DEXSCREENER_BASE}/{addr_str}", timeout=15.0
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            continue

        # Group pairs by base token mint
        by_mint: dict[str, list[dict]] = {}
        for pair in data.get("pairs") or []:
            mint = (pair.get("baseToken") or {}).get("address", "")
            if mint in batch:
                by_mint.setdefault(mint, []).append(pair)

        for mint, mint_pairs in by_mint.items():
            best = _pick_best_pair(mint_pairs)
            if best:
                result[mint] = _parse_pair(best)

    return result
