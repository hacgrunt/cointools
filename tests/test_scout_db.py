"""Tests for scout.db module."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from cointools.scout.db import (
    add_wallet,
    get_scout_connection,
    get_token_aggregation,
    get_trades_since,
    list_wallets,
    remove_wallet,
    update_wallet_scan_time,
    upsert_trades,
)


@pytest.fixture
def conn():
    """Provide a fresh in-memory scout DB connection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        c = get_scout_connection(db_path)
        yield c
        c.close()


class TestWalletCRUD:
    def test_add_wallet(self, conn):
        assert add_wallet(conn, "WALLET_A", "alpha") is True
        wallets = list_wallets(conn)
        assert len(wallets) == 1
        assert wallets[0]["address"] == "WALLET_A"
        assert wallets[0]["label"] == "alpha"

    def test_add_duplicate_returns_false(self, conn):
        add_wallet(conn, "WALLET_A", "alpha")
        assert add_wallet(conn, "WALLET_A", "beta") is False

    def test_add_duplicate_reactivates(self, conn):
        add_wallet(conn, "WALLET_A", "alpha")
        remove_wallet(conn, "WALLET_A")
        assert list_wallets(conn) == []
        add_wallet(conn, "WALLET_A")
        wallets = list_wallets(conn)
        assert len(wallets) == 1
        assert wallets[0]["is_active"] == 1

    def test_remove_wallet(self, conn):
        add_wallet(conn, "WALLET_A")
        assert remove_wallet(conn, "WALLET_A") is True
        assert list_wallets(conn) == []

    def test_remove_nonexistent(self, conn):
        assert remove_wallet(conn, "NOPE") is False

    def test_list_wallets_active_only(self, conn):
        add_wallet(conn, "A")
        add_wallet(conn, "B")
        remove_wallet(conn, "A")
        assert len(list_wallets(conn, active_only=True)) == 1
        assert len(list_wallets(conn, active_only=False)) == 2

    def test_update_scan_time(self, conn):
        add_wallet(conn, "WALLET_A")
        update_wallet_scan_time(conn, "WALLET_A")
        w = list_wallets(conn)[0]
        assert w["last_scanned"] is not None


class TestTrades:
    def _make_trade(self, wallet="W1", sig="sig1", ts=1000, ttype="BUY",
                    mint="TOKEN_A", amount=100.0, sol=1.5, source="JUPITER"):
        return {
            "wallet_address": wallet,
            "signature": sig,
            "timestamp": ts,
            "trade_type": ttype,
            "token_mint": mint,
            "token_amount": amount,
            "sol_amount": sol,
            "source": source,
        }

    def test_upsert_trades(self, conn):
        trades = [self._make_trade(sig="s1"), self._make_trade(sig="s2")]
        assert upsert_trades(conn, trades) == 2

    def test_upsert_skips_duplicates(self, conn):
        trades = [self._make_trade(sig="s1")]
        upsert_trades(conn, trades)
        assert upsert_trades(conn, trades) == 0

    def test_get_trades_since(self, conn):
        trades = [
            self._make_trade(sig="s1", ts=500),
            self._make_trade(sig="s2", ts=1000),
            self._make_trade(sig="s3", ts=1500),
        ]
        upsert_trades(conn, trades)
        result = get_trades_since(conn, 900)
        assert len(result) == 2

    def test_get_trades_filter_by_wallet(self, conn):
        trades = [
            self._make_trade(wallet="W1", sig="s1", ts=1000),
            self._make_trade(wallet="W2", sig="s2", ts=1000),
        ]
        upsert_trades(conn, trades)
        result = get_trades_since(conn, 0, wallet_address="W1")
        assert len(result) == 1
        assert result[0]["wallet_address"] == "W1"

    def test_get_trades_filter_by_token(self, conn):
        trades = [
            self._make_trade(sig="s1", mint="T1", ts=1000),
            self._make_trade(sig="s2", mint="T2", ts=1000),
        ]
        upsert_trades(conn, trades)
        result = get_trades_since(conn, 0, token_mint="T2")
        assert len(result) == 1
        assert result[0]["token_mint"] == "T2"


class TestAggregation:
    def _make_trade(self, wallet, sig, mint, ttype, sol=1.0, ts=1000):
        return {
            "wallet_address": wallet,
            "signature": sig,
            "timestamp": ts,
            "trade_type": ttype,
            "token_mint": mint,
            "token_amount": 100.0,
            "sol_amount": sol,
            "source": "JUPITER",
        }

    def test_aggregation_basic(self, conn):
        trades = [
            self._make_trade("W1", "s1", "TOKEN_A", "BUY", sol=2.0),
            self._make_trade("W2", "s2", "TOKEN_A", "BUY", sol=3.0),
            self._make_trade("W1", "s3", "TOKEN_A", "SELL", sol=1.0),
            self._make_trade("W1", "s4", "TOKEN_B", "BUY", sol=5.0),
        ]
        upsert_trades(conn, trades)
        agg = get_token_aggregation(conn, 0)

        # TOKEN_A has 2 unique buyers, should be first
        assert agg[0]["token_mint"] == "TOKEN_A"
        assert agg[0]["unique_buyers"] == 2
        assert agg[0]["buy_count"] == 2
        assert agg[0]["sell_count"] == 1
        assert agg[0]["total_sol_in"] == 5.0
        assert agg[0]["total_sol_out"] == 1.0

        # TOKEN_B has 1 unique buyer
        assert agg[1]["token_mint"] == "TOKEN_B"
        assert agg[1]["unique_buyers"] == 1

    def test_aggregation_respects_since(self, conn):
        trades = [
            self._make_trade("W1", "s1", "TOKEN_A", "BUY", ts=500),
            self._make_trade("W1", "s2", "TOKEN_A", "BUY", ts=1500),
        ]
        upsert_trades(conn, trades)
        agg = get_token_aggregation(conn, 1000)
        assert len(agg) == 1
        assert agg[0]["buy_count"] == 1
