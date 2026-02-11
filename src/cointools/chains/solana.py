"""Solana RPC client for fetching top holders and historical balances."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

# Solana RPC requests per second budget (conservative for public endpoint)
_RPC_DELAY = 0.12  # ~8 req/s


@dataclass
class HolderInfo:
    token_account: str
    owner: str | None
    balance_raw: int
    balance_ui: float
    decimals: int
    rank: int


async def _rpc_call(
    client: httpx.AsyncClient,
    rpc_url: str,
    method: str,
    params: list,
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
    return data["result"]


async def get_top_holders(
    client: httpx.AsyncClient, rpc_url: str, mint: str
) -> list[HolderInfo]:
    """Fetch the top 20 holders of a token via getTokenLargestAccounts."""
    result = await _rpc_call(
        client, rpc_url, "getTokenLargestAccounts", [mint]
    )
    holders = []
    for i, item in enumerate(result["value"], start=1):
        holders.append(
            HolderInfo(
                token_account=item["address"],
                owner=None,  # resolved later
                balance_raw=int(item["amount"]),
                balance_ui=float(item["uiAmountString"]),
                decimals=item["decimals"],
                rank=i,
            )
        )
    return holders


async def resolve_owner(
    client: httpx.AsyncClient, rpc_url: str, token_account: str
) -> str | None:
    """Resolve the owner wallet of a token account via getAccountInfo."""
    result = await _rpc_call(
        client,
        rpc_url,
        "getAccountInfo",
        [token_account, {"encoding": "jsonParsed"}],
    )
    if result and result.get("value"):
        info = result["value"].get("data", {})
        if isinstance(info, dict) and "parsed" in info:
            return info["parsed"]["info"].get("owner")
    return None


async def get_signatures_for_account(
    client: httpx.AsyncClient,
    rpc_url: str,
    account: str,
    *,
    limit: int = 1000,
    before: str | None = None,
) -> list[dict]:
    """Get transaction signatures for a token account, newest first."""
    opts: dict = {"limit": limit}
    if before:
        opts["before"] = before
    return await _rpc_call(
        client, rpc_url, "getSignaturesForAddress", [account, opts]
    )


async def get_transaction(
    client: httpx.AsyncClient, rpc_url: str, signature: str
) -> dict | None:
    """Fetch a parsed transaction by signature."""
    result = await _rpc_call(
        client,
        rpc_url,
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
    )
    return result


def _extract_balance_for_account(
    tx: dict, token_account: str
) -> float | None:
    """Extract postTokenBalance for a specific account from a transaction."""
    meta = tx.get("meta") or {}
    post_balances = meta.get("postTokenBalances") or []
    # Build a list of account keys from the transaction
    account_keys = []
    msg = tx.get("transaction", {}).get("message", {})
    for key in msg.get("accountKeys", []):
        if isinstance(key, dict):
            account_keys.append(key.get("pubkey", ""))
        else:
            account_keys.append(key)

    for bal in post_balances:
        idx = bal.get("accountIndex", -1)
        if 0 <= idx < len(account_keys) and account_keys[idx] == token_account:
            ui = bal.get("uiTokenAmount", {})
            amount_str = ui.get("uiAmountString")
            if amount_str is not None:
                return float(amount_str)
    return None


async def find_historical_balance(
    client: httpx.AsyncClient,
    rpc_url: str,
    token_account: str,
    target_timestamp: int,
) -> float | None:
    """Find the balance of a token account at approximately `target_timestamp`.

    Walks backwards through transaction signatures until we find one at or
    before the target time, then extracts the postTokenBalance from that tx.
    """
    before_sig: str | None = None

    for _ in range(5):  # max 5 pages of 1000 signatures
        await asyncio.sleep(_RPC_DELAY)
        sigs = await get_signatures_for_account(
            client, rpc_url, token_account, limit=1000, before=before_sig
        )
        if not sigs:
            return None

        # Signatures are newest-first. Find the first one at or before target.
        best_sig = None
        for sig_info in sigs:
            block_time = sig_info.get("blockTime")
            if block_time is None:
                continue
            if block_time <= target_timestamp:
                best_sig = sig_info["signature"]
                break
            # Also keep the sig closest to target even if after
            before_sig = sig_info["signature"]

        if best_sig:
            await asyncio.sleep(_RPC_DELAY)
            tx = await get_transaction(client, rpc_url, best_sig)
            if tx:
                bal = _extract_balance_for_account(tx, token_account)
                if bal is not None:
                    return bal
            return None

        # If we've gone past the target without finding, check last sig time
        last_time = sigs[-1].get("blockTime") or 0
        if last_time < target_timestamp:
            # Went too far back. Use the earliest sig we have that's after target.
            # Fetch the transaction for the last sig of the previous page
            for sig_info in reversed(sigs):
                bt = sig_info.get("blockTime")
                if bt and bt >= target_timestamp:
                    await asyncio.sleep(_RPC_DELAY)
                    tx = await get_transaction(client, rpc_url, sig_info["signature"])
                    if tx:
                        bal = _extract_balance_for_account(tx, token_account)
                        if bal is not None:
                            return bal
                    break
            return None

    return None


async def analyze_holders(
    rpc_url: str,
    mint: str,
    period_seconds: int,
    on_progress: callable | None = None,
) -> list[dict]:
    """Full analysis: get top holders and their historical balances.

    Returns a list of dicts with keys:
        holder_address, owner_address, current_balance, historical_balance, rank
    """
    target_time = int(time.time()) - period_seconds

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Get current top holders
        holders = await get_top_holders(client, rpc_url, mint)

        # Step 2: Resolve owners in parallel (batched to respect rate limits)
        async def resolve_one(h: HolderInfo) -> None:
            await asyncio.sleep(_RPC_DELAY)
            h.owner = await resolve_owner(client, rpc_url, h.token_account)

        await asyncio.gather(*[resolve_one(h) for h in holders])

        if on_progress:
            on_progress("Fetched top 20 holders, resolving history...")

        # Step 3: Find historical balances in parallel
        async def find_one(h: HolderInfo) -> dict:
            hist = await find_historical_balance(
                client, rpc_url, h.token_account, target_time
            )
            return {
                "holder_address": h.token_account,
                "owner_address": h.owner,
                "current_balance": h.balance_ui,
                "historical_balance": hist,
                "rank": h.rank,
                "decimals": h.decimals,
            }

        results = await asyncio.gather(*[find_one(h) for h in holders])

    return list(results)
