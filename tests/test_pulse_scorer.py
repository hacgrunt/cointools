"""Tests for pulse attention scoring engine."""

from __future__ import annotations

import time

from cointools.pulse.scorer import (
    filter_token,
    score_and_rank,
    score_token,
)


def _make_token(**overrides) -> dict:
    """Create a token snapshot with sensible defaults."""
    base = {
        "address": "So11111111111111111111111111111111111111111",
        "name": "TestToken",
        "symbol": "TEST",
        "price_usd": 0.001,
        "market_cap": 500_000,
        "liquidity_usd": 50_000,
        "volume_m5": 5_000,
        "volume_h1": 30_000,
        "volume_h6": 150_000,
        "volume_h24": 500_000,
        "buys_m5": 20,
        "sells_m5": 10,
        "buys_h1": 120,
        "sells_h1": 60,
        "buys_h6": 500,
        "sells_h6": 300,
        "buys_h24": 1500,
        "sells_h24": 1000,
        "price_change_m5": 3.0,
        "price_change_h1": 10.0,
        "price_change_h6": 20.0,
        "price_change_h24": 30.0,
        # Created 2 hours ago
        "pair_created_at": int((time.time() - 7200) * 1000),
        "boost_active": 0,
        "boost_total": 0,
        "pair_url": "https://dexscreener.com/solana/test",
        "dex": "raydium",
        "pair_address": "pair123",
    }
    base.update(overrides)
    return base


# ── Filter tests ─────────────────────────────────────────────────


class TestFilterToken:
    def test_passes_normal_token(self):
        assert filter_token(_make_token()) is True

    def test_rejects_low_liquidity(self):
        assert filter_token(_make_token(liquidity_usd=500)) is False

    def test_rejects_high_mcap(self):
        assert filter_token(_make_token(market_cap=100_000_000)) is False

    def test_rejects_old_token(self):
        old_ts = int((time.time() - 80 * 3600) * 1000)  # 80 hours ago
        assert filter_token(_make_token(pair_created_at=old_ts)) is False

    def test_rejects_zero_txns(self):
        assert filter_token(_make_token(buys_m5=0, sells_m5=0)) is False

    def test_custom_thresholds(self):
        token = _make_token(liquidity_usd=500, market_cap=200_000_000)
        assert filter_token(token, min_liquidity=100, max_market_cap=1e9) is True


# ── Score tests ──────────────────────────────────────────────────


class TestScoreToken:
    def test_returns_all_fields(self):
        result = score_token(_make_token())
        assert "score" in result
        assert "components" in result
        assert "age_factor" in result
        assert "vol_ratio" in result
        assert "txn_ratio" in result
        assert "buy_pressure" in result
        # Components
        comp = result["components"]
        assert "volume_accel" in comp
        assert "txn_accel" in comp
        assert "boost" in comp
        assert "momentum" in comp
        assert "vol_liq" in comp

    def test_score_nonnegative(self):
        result = score_token(_make_token())
        assert result["score"] >= 0

    def test_high_volume_accel_scores_higher(self):
        normal = score_token(_make_token(volume_m5=2500, volume_h1=30000))
        hot = score_token(_make_token(volume_m5=15000, volume_h1=30000))
        assert hot["score"] > normal["score"]
        assert hot["components"]["volume_accel"] > normal["components"]["volume_accel"]

    def test_high_txn_accel_scores_higher(self):
        normal = score_token(_make_token(buys_m5=10, sells_m5=5, buys_h1=120, sells_h1=60))
        hot = score_token(_make_token(buys_m5=60, sells_m5=30, buys_h1=120, sells_h1=60))
        assert hot["score"] > normal["score"]
        assert hot["components"]["txn_accel"] > normal["components"]["txn_accel"]

    def test_boost_increases_score(self):
        no_boost = score_token(_make_token(boost_active=0))
        boosted = score_token(_make_token(boost_active=5))
        assert boosted["score"] > no_boost["score"]
        assert boosted["components"]["boost"] == 20  # 5 * 4 = 20

    def test_newer_token_scores_higher(self):
        young_ts = int((time.time() - 0.5 * 3600) * 1000)  # 30 min
        old_ts = int((time.time() - 72 * 3600) * 1000)  # 72 hours
        young = score_token(_make_token(pair_created_at=young_ts))
        old = score_token(_make_token(pair_created_at=old_ts))
        assert young["age_factor"] > old["age_factor"]
        assert young["score"] > old["score"]

    def test_zero_volume_doesnt_crash(self):
        result = score_token(_make_token(
            volume_m5=0, volume_h1=0, volume_h6=0, volume_h24=0,
            buys_m5=1, sells_m5=0, buys_h1=0, sells_h1=0,
        ))
        assert result["score"] >= 0

    def test_buy_pressure(self):
        result = score_token(_make_token(buys_m5=20, sells_m5=10))
        assert abs(result["buy_pressure"] - 0.67) < 0.02

    def test_vol_ratio_calculation(self):
        # vol_m5=5000, vol_h1=30000, so h1_avg_5m = 2500, ratio = 2.0
        result = score_token(_make_token(volume_m5=5000, volume_h1=30000))
        assert abs(result["vol_ratio"] - 2.0) < 0.01


# ── Rank tests ───────────────────────────────────────────────────


class TestScoreAndRank:
    def test_sorts_by_score_desc(self):
        tokens = [
            _make_token(address="a", volume_m5=1000, volume_h1=30000),
            _make_token(address="b", volume_m5=15000, volume_h1=30000),
            _make_token(address="c", volume_m5=8000, volume_h1=30000),
        ]
        ranked = score_and_rank(tokens)
        scores = [t["score"] for t in ranked]
        assert scores == sorted(scores, reverse=True)
        assert ranked[0]["address"] == "b"

    def test_filters_applied(self):
        tokens = [
            _make_token(address="good", liquidity_usd=50000),
            _make_token(address="bad", liquidity_usd=100),
        ]
        ranked = score_and_rank(tokens)
        assert len(ranked) == 1
        assert ranked[0]["address"] == "good"

    def test_empty_input(self):
        assert score_and_rank([]) == []

    def test_merges_score_into_token(self):
        tokens = [_make_token()]
        ranked = score_and_rank(tokens)
        assert len(ranked) == 1
        t = ranked[0]
        # Has both original and scored fields
        assert "address" in t
        assert "symbol" in t
        assert "score" in t
        assert "components" in t
