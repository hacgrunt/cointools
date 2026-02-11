"""Tests for the EVM chain client (mocked)."""

from unittest.mock import AsyncMock

import httpx
import pytest

from cointools.chains.evm import (
    EVMHolderInfo,
    get_balance_at_block,
    get_latest_block,
    get_token_decimals,
    get_top_holders,
)


def _mock_response(result):
    resp = AsyncMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": result}
    resp.raise_for_status = lambda: None
    return resp


class TestGetTopHolders:
    @pytest.mark.asyncio
    async def test_parses_ankr_response(self):
        ankr_result = {
            "holders": [
                {
                    "holderAddress": "0xabc123",
                    "balance": "1000000000000000000000",
                },
                {
                    "holderAddress": "0xdef456",
                    "balance": "500000000000000000000",
                },
            ]
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(ankr_result)

        holders, decimals = await get_top_holders(client, "base", "0xtoken")

        assert len(holders) == 2
        assert holders[0].holder_address == "0xabc123"
        assert holders[0].rank == 1
        assert holders[1].holder_address == "0xdef456"
        assert holders[1].rank == 2

    @pytest.mark.asyncio
    async def test_empty_holders(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response({"holders": []})

        holders, decimals = await get_top_holders(client, "base", "0xtoken")
        assert holders == []


class TestGetTokenDecimals:
    @pytest.mark.asyncio
    async def test_parses_decimals(self):
        # 18 in hex = 0x12
        hex_18 = "0x0000000000000000000000000000000000000000000000000000000000000012"
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(hex_18)

        decimals = await get_token_decimals(client, "http://rpc", "0xtoken")
        assert decimals == 18

    @pytest.mark.asyncio
    async def test_defaults_to_18(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response("0x")

        decimals = await get_token_decimals(client, "http://rpc", "0xtoken")
        assert decimals == 18


class TestGetLatestBlock:
    @pytest.mark.asyncio
    async def test_parses_block_number(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        # 1000000 in hex
        client.post.return_value = _mock_response("0xf4240")

        block = await get_latest_block(client, "http://rpc")
        assert block == 1000000


class TestGetBalanceAtBlock:
    @pytest.mark.asyncio
    async def test_parses_balance(self):
        # 1000 * 10^18 in hex
        balance_hex = hex(1000 * 10**18)
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response(balance_hex)

        balance = await get_balance_at_block(
            client, "http://rpc", "0xtoken", "0xholder", 999000
        )
        assert balance == 1000 * 10**18

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = _mock_response("0x")

        balance = await get_balance_at_block(
            client, "http://rpc", "0xtoken", "0xholder", 999000
        )
        assert balance == 0
