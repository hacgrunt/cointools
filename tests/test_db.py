"""Tests for the database cache layer."""

import sqlite3
from pathlib import Path

from cointools.db import get_connection, get_latest_analysis, save_analysis


def _tmp_db(tmp_path: Path) -> sqlite3.Connection:
    return get_connection(tmp_path / "test.db")


def _sample_holders():
    return [
        {
            "holder_address": "acc1",
            "owner_address": "owner1",
            "current_balance": 1000.0,
            "historical_balance": 500.0,
            "rank": 1,
        },
        {
            "holder_address": "acc2",
            "owner_address": "owner2",
            "current_balance": 800.0,
            "historical_balance": 900.0,
            "rank": 2,
        },
    ]


class TestSaveAndRetrieve:
    def test_save_and_get(self, tmp_path):
        conn = _tmp_db(tmp_path)
        holders = _sample_holders()
        save_analysis(conn, "mintXYZ", "24h", holders)

        result = get_latest_analysis(conn, "mintXYZ", "24h")
        assert result is not None
        assert len(result) == 2
        assert result[0]["mint_address"] == "mintXYZ"
        assert result[0]["current_balance"] == 1000.0
        conn.close()

    def test_returns_none_when_empty(self, tmp_path):
        conn = _tmp_db(tmp_path)
        result = get_latest_analysis(conn, "nonexistent", "24h")
        assert result is None
        conn.close()

    def test_latest_only(self, tmp_path):
        conn = _tmp_db(tmp_path)
        # Save two rounds
        save_analysis(conn, "mintA", "7d", _sample_holders())
        save_analysis(conn, "mintA", "7d", [
            {
                "holder_address": "acc1",
                "owner_address": "owner1",
                "current_balance": 2000.0,
                "historical_balance": 1000.0,
                "rank": 1,
            },
        ])

        result = get_latest_analysis(conn, "mintA", "7d")
        assert result is not None
        # Should return the latest entry (2000 balance)
        assert result[0]["current_balance"] == 2000.0
        conn.close()

    def test_different_periods_isolated(self, tmp_path):
        conn = _tmp_db(tmp_path)
        save_analysis(conn, "mintB", "24h", _sample_holders())

        result_7d = get_latest_analysis(conn, "mintB", "7d")
        assert result_7d is None

        result_24h = get_latest_analysis(conn, "mintB", "24h")
        assert result_24h is not None
        conn.close()
