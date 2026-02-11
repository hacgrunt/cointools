"""EVM chain client for fetching top holders and historical balances.

Uses Ankr's free multichain API for top holders (no API key required)
and standard EVM JSON-RPC for historical balance lookups.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

ANKR_MULTICHAIN_URL = "https://rpc.ankr.com/multichain"

# ERC-20 function selectors
BALANCE_OF_SELECTOR = "0x70a08231"
DECIMALS_SELECTOR = "0x313ce567"

# Approximate block times in seconds for supported chains
CHAIN_BLOCK_TIMES: dict[str, float] = {
    "base": 2.0,
    "eth": 12.0,
    "optimism": 2.0,
    "arbitrum": 0.25,
    "polygon": 2.0,
    "bsc": 3.0,
}

# Ankr chain identifiers
CHAIN_RPC_URLS: dict[str, str] = {
    "base": "https://rpc.ankr.com/base",
    "eth": "https://rpc.ankr.com/eth",
    "optimism": "https://rpc.ankr.com/optimism",
    "arbitrum": "https://rpc.ankr.com/arbitrum",
    "polygon": "https://rpc.ankr.com/polygon",
    "bsc": "https://rpc.ankr.com/bsc",
}

_RPC_DELAY = 0.15


@dataclass
class EVMHolderInfo:
    holder_address: str
    balance_raw: str
    balance_ui: float
    decimals: int
    rank: int


async def _ankr_call(
    client: httpx.AsyncClient, method: str, params: dict
) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    resp = await client.post(ANKR_MULTICHAIN_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Ankr API error: {data['error']}")
    return data.get("result", {})


async def _eth_rpc_call(
    client: httpx.AsyncClient, rpc_url: str, method: str, params: list
) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    resp = await client.post(rpc_url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data.get("result")


async def get_top_holders(
    client: httpx.AsyncClient, chain: str, contract: str, page_size: int = 20
) -> tuple[list[EVMHolderInfo], int]:
    """Fetch top holders via Ankr's ankr_getTokenHolders.

    Returns (holders, decimals).
    """
    result = await _ankr_call(
        client,
        "ankr_getTokenHolders",
        {
            "blockchain": chain,
            "contractAddress": contract,
            "pageSize": page_size,
        },
    )

    holders_raw = result.get("holders", [])
    if not holders_raw:
        return [], 18

    # Get token decimals from the first holder or default to 18
    decimals = 18
    # Ankr returns holders sorted by balance descending
    holders = []
    for i, h in enumerate(holders_raw[:page_size], start=1):
        balance_raw = h.get("balance", "0")
        # Ankr returns balances as raw integer strings
        try:
            balance_int = int(balance_raw)
        except (ValueError, TypeError):
            # Sometimes Ankr returns floating-point strings
            try:
                balance_int = int(float(balance_raw))
            except (ValueError, TypeError):
                balance_int = 0

        holders.append(
            EVMHolderInfo(
                holder_address=h.get("holderAddress", ""),
                balance_raw=balance_raw,
                balance_ui=0.0,  # will be computed after getting decimals
                decimals=decimals,
                rank=i,
            )
        )

    return holders, decimals


async def get_token_decimals(
    client: httpx.AsyncClient, rpc_url: str, contract: str
) -> int:
    """Get ERC-20 token decimals."""
    result = await _eth_rpc_call(
        client,
        rpc_url,
        "eth_call",
        [{"to": contract, "data": DECIMALS_SELECTOR}, "latest"],
    )
    if result and result != "0x":
        return int(result, 16)
    return 18


async def get_latest_block(
    client: httpx.AsyncClient, rpc_url: str
) -> int:
    result = await _eth_rpc_call(client, rpc_url, "eth_blockNumber", [])
    return int(result, 16)


async def get_balance_at_block(
    client: httpx.AsyncClient,
    rpc_url: str,
    contract: str,
    holder: str,
    block: int,
) -> int:
    """Call ERC-20 balanceOf(holder) at a specific block."""
    # Encode: balanceOf(address) = 0x70a08231 + address padded to 32 bytes
    padded = holder.lower().replace("0x", "").zfill(64)
    data = BALANCE_OF_SELECTOR + padded
    block_hex = hex(block)

    result = await _eth_rpc_call(
        client,
        rpc_url,
        "eth_call",
        [{"to": contract, "data": data}, block_hex],
    )
    if result and result != "0x":
        return int(result, 16)
    return 0


async def analyze_holders(
    chain: str,
    contract: str,
    period_seconds: int,
    rpc_url: str | None = None,
    on_progress: callable | None = None,
) -> list[dict]:
    """Full EVM analysis: get top holders and their historical balances.

    Returns a list of dicts compatible with the tracker module.
    """
    evm_rpc = rpc_url or CHAIN_RPC_URLS.get(chain, CHAIN_RPC_URLS["base"])
    block_time = CHAIN_BLOCK_TIMES.get(chain, 2.0)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Get current top holders from Ankr
        if on_progress:
            on_progress("Fetching top holders from Ankr...")

        holders, _decimals = await get_top_holders(client, chain, contract)
        if not holders:
            return []

        # Step 2: Get token decimals and current block
        decimals = await get_token_decimals(client, evm_rpc, contract)
        current_block = await get_latest_block(client, evm_rpc)
        blocks_back = int(period_seconds / block_time)
        historical_block = max(1, current_block - blocks_back)

        # Update holder balances with proper decimals
        for h in holders:
            try:
                h.balance_ui = int(h.balance_raw) / (10 ** decimals)
            except (ValueError, TypeError):
                try:
                    h.balance_ui = float(h.balance_raw) / (10 ** decimals)
                except (ValueError, TypeError):
                    h.balance_ui = 0.0
            h.decimals = decimals

        if on_progress:
            on_progress(
                f"Fetched {len(holders)} holders, looking up history "
                f"(block {historical_block})..."
            )

        # Step 3: Get historical balances in parallel
        async def get_historical(h: EVMHolderInfo) -> dict:
            await asyncio.sleep(_RPC_DELAY)
            try:
                hist_raw = await get_balance_at_block(
                    client, evm_rpc, contract, h.holder_address, historical_block
                )
                hist_ui = hist_raw / (10 ** decimals)
            except Exception:
                hist_ui = None

            return {
                "holder_address": h.holder_address,
                "owner_address": h.holder_address,  # on EVM, holder IS the owner
                "current_balance": h.balance_ui,
                "historical_balance": hist_ui,
                "rank": h.rank,
                "decimals": decimals,
            }

        results = await asyncio.gather(*[get_historical(h) for h in holders])

    return list(results)
