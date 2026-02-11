"""Tests for the Solana RPC client (mocked)."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cointools.chains.solana import (
    HolderInfo,
    _extract_balance_for_account,
    get_top_holders,
    resolve_owner,
)


def _mock_response(result):
    """Create a mock httpx.Response with a JSON-RPC result."""
    resp = AsyncMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": result}
    resp.raise_for_status = lambda: None
    return resp


class TestGetTopHolders:
    @pytest.mark.asyncio
    async def test_parses_response(self):
        mock_result = {
            "value": [
                {
                    "address": "tokenAcc1",
                    "amount": "1000000000",
                    "decimals": 6,
                    "uiAmountString": "1000.0",
                },
                {
                    "address": "tokenAcc2",
                    "amount": "500000000",
                    "decimals": 6,
                    "uiAmountString": "500.0",
                },
            ]
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(mock_result)

        holders = await get_top_holders(client, "http://rpc", "mintAddr")

        assert len(holders) == 2
        assert holders[0].token_account == "tokenAcc1"
        assert holders[0].balance_ui == 1000.0
        assert holders[0].rank == 1
        assert holders[1].token_account == "tokenAcc2"
        assert holders[1].balance_ui == 500.0
        assert holders[1].rank == 2


class TestResolveOwner:
    @pytest.mark.asyncio
    async def test_resolves_owner(self):
        mock_result = {
            "value": {
                "data": {
                    "parsed": {
                        "info": {"owner": "walletABC"},
                        "type": "account",
                    },
                    "program": "spl-token",
                },
                "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            }
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(mock_result)

        owner = await resolve_owner(client, "http://rpc", "tokenAcc1")
        assert owner == "walletABC"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self):
        mock_result = {"value": None}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(mock_result)

        owner = await resolve_owner(client, "http://rpc", "tokenAcc1")
        assert owner is None


class TestExtractBalance:
    def test_finds_balance(self):
        tx = {
            "transaction": {
                "message": {
                    "accountKeys": [
                        {"pubkey": "signer1"},
                        {"pubkey": "tokenAcc1"},
                        {"pubkey": "program1"},
                    ]
                }
            },
            "meta": {
                "postTokenBalances": [
                    {
                        "accountIndex": 1,
                        "uiTokenAmount": {
                            "uiAmountString": "1500.5",
                            "decimals": 6,
                        },
                    }
                ]
            },
        }
        result = _extract_balance_for_account(tx, "tokenAcc1")
        assert result == 1500.5

    def test_returns_none_when_not_found(self):
        tx = {
            "transaction": {
                "message": {
                    "accountKeys": [{"pubkey": "other"}]
                }
            },
            "meta": {"postTokenBalances": []},
        }
        result = _extract_balance_for_account(tx, "tokenAcc1")
        assert result is None

    def test_handles_missing_meta(self):
        tx = {"transaction": {"message": {"accountKeys": []}}, "meta": None}
        result = _extract_balance_for_account(tx, "tokenAcc1")
        assert result is None
