"""DexScreener API poller for token discovery and enrichment."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BOOST_LATEST_URL = "https://api.dexscreener.com/token-boosts/latest/v1"
BOOST_TOP_URL = "https://api.dexscreener.com/token-boosts/top/v1"
PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
TOKEN_DATA_URL = "https://api.dexscreener.com/latest/dex/tokens"

_BATCH_SIZE = 30  # DexScreener max addresses per request
_API_DELAY = 0.35  # delay between batch requests


def _extract_solana_addresses(items: list[dict]) -> dict[str, dict]:
    """Extract Solana token addresses from boost/profile responses.

    Returns mapping of address → metadata (boost amount, etc).
    """
    result: dict[str, dict] = {}
    for item in items:
        if item.get("chainId") != "solana":
            continue
        addr = item.get("tokenAddress", "")
        if not addr:
            continue
        existing = result.get(addr, {})
        # Merge boost amounts (take the higher)
        amount = item.get("amount", 0) or 0
        total = item.get("totalAmount", 0) or 0
        existing["boost_amount"] = max(existing.get("boost_amount", 0), amount)
        existing["boost_total"] = max(existing.get("boost_total", 0), total)
        existing["has_profile"] = existing.get("has_profile", False) or ("description" in item)
        result[addr] = existing
    return result


def _pick_best_pair(pairs: list[dict]) -> dict | None:
    """Select the highest-liquidity Solana pair for a token."""
    solana = [p for p in pairs if p.get("chainId") == "solana"]
    candidates = solana or pairs
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda p: float((p.get("liquidity") or {}).get("usd", 0) or 0),
    )


def _parse_pair(pair: dict, discovery_meta: dict) -> dict[str, Any]:
    """Parse a DexScreener pair into a flat token snapshot dict."""
    base = pair.get("baseToken") or {}
    liq = pair.get("liquidity") or {}
    vol = pair.get("volume") or {}
    txns = pair.get("txns") or {}
    pc = pair.get("priceChange") or {}
    boosts = pair.get("boosts") or {}

    m5_txns = txns.get("m5") or {}
    h1_txns = txns.get("h1") or {}
    h6_txns = txns.get("h6") or {}
    h24_txns = txns.get("h24") or {}

    return {
        "address": base.get("address", ""),
        "name": base.get("name", "Unknown"),
        "symbol": base.get("symbol", "???"),
        "price_usd": float(pair.get("priceUsd") or 0),
        "market_cap": float(pair.get("marketCap") or pair.get("fdv") or 0),
        "liquidity_usd": float(liq.get("usd") or 0),
        # Volume windows
        "volume_m5": float(vol.get("m5") or 0),
        "volume_h1": float(vol.get("h1") or 0),
        "volume_h6": float(vol.get("h6") or 0),
        "volume_h24": float(vol.get("h24") or 0),
        # Transaction windows
        "buys_m5": int(m5_txns.get("buys") or 0),
        "sells_m5": int(m5_txns.get("sells") or 0),
        "buys_h1": int(h1_txns.get("buys") or 0),
        "sells_h1": int(h1_txns.get("sells") or 0),
        "buys_h6": int(h6_txns.get("buys") or 0),
        "sells_h6": int(h6_txns.get("sells") or 0),
        "buys_h24": int(h24_txns.get("buys") or 0),
        "sells_h24": int(h24_txns.get("sells") or 0),
        # Price changes
        "price_change_m5": float(pc.get("m5") or 0),
        "price_change_h1": float(pc.get("h1") or 0),
        "price_change_h6": float(pc.get("h6") or 0),
        "price_change_h24": float(pc.get("h24") or 0),
        # Metadata
        "pair_created_at": int(pair.get("pairCreatedAt") or 0),
        "boost_active": int(boosts.get("active") or 0),
        "boost_total": discovery_meta.get("boost_total", 0),
        "pair_url": pair.get("url", ""),
        "dex": pair.get("dexId", ""),
        "pair_address": pair.get("pairAddress", ""),
    }


class PulseScanner:
    """Polls DexScreener APIs to discover and enrich Solana tokens."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _fetch_json(self, url: str) -> list | dict:
        client = await self._get_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return []

    async def discover(self) -> dict[str, dict]:
        """Discover Solana tokens from boosts and profiles.

        Returns mapping of token_address → discovery metadata.
        """
        # Fetch all discovery sources in parallel
        boost_latest, boost_top, profiles = await asyncio.gather(
            self._fetch_json(BOOST_LATEST_URL),
            self._fetch_json(BOOST_TOP_URL),
            self._fetch_json(PROFILES_URL),
        )

        # Ensure list types
        if not isinstance(boost_latest, list):
            boost_latest = []
        if not isinstance(boost_top, list):
            boost_top = []
        if not isinstance(profiles, list):
            profiles = []

        # Extract Solana addresses and merge metadata
        discovered: dict[str, dict] = {}
        for source in (boost_latest, boost_top, profiles):
            for addr, meta in _extract_solana_addresses(source).items():
                existing = discovered.get(addr, {})
                existing["boost_amount"] = max(
                    existing.get("boost_amount", 0), meta.get("boost_amount", 0)
                )
                existing["boost_total"] = max(
                    existing.get("boost_total", 0), meta.get("boost_total", 0)
                )
                existing["has_profile"] = existing.get("has_profile", False) or meta.get(
                    "has_profile", False
                )
                discovered[addr] = existing

        logger.info("Discovered %d Solana tokens", len(discovered))
        return discovered

    async def enrich(self, discovered: dict[str, dict]) -> list[dict]:
        """Fetch full pair data for discovered tokens.

        Returns list of enriched token snapshot dicts.
        """
        if not discovered:
            return []

        addresses = list(discovered.keys())
        client = await self._get_client()
        result: list[dict] = []

        for i in range(0, len(addresses), _BATCH_SIZE):
            batch = addresses[i : i + _BATCH_SIZE]
            addr_str = ",".join(batch)

            if i > 0:
                await asyncio.sleep(_API_DELAY)

            try:
                resp = await client.get(f"{TOKEN_DATA_URL}/{addr_str}", timeout=15.0)
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                logger.warning("Failed to enrich batch %d: %s", i, e)
                continue

            # Group pairs by base token
            by_token: dict[str, list[dict]] = {}
            for pair in data.get("pairs") or []:
                mint = (pair.get("baseToken") or {}).get("address", "")
                if mint in discovered:
                    by_token.setdefault(mint, []).append(pair)

            for mint, pairs in by_token.items():
                best = _pick_best_pair(pairs)
                if best:
                    meta = discovered.get(mint, {})
                    result.append(_parse_pair(best, meta))

        return result

    async def poll(self) -> list[dict]:
        """Full poll cycle: discover + enrich."""
        discovered = await self.discover()
        return await self.enrich(discovered)
