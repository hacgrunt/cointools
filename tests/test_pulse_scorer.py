"""Tests for pulse accumulation scoring engine."""

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
        "market_cap": 150_000,  # $150K — in the sweet spot
        "liquidity_usd": 25_000,
        "volume_m5": 2_000,
        "volume_h1": 15_000,
        "volume_h6": 60_000,
        "volume_h24": 180_000,
        "buys_m5": 12,
        "sells_m5": 8,
        "buys_h1": 80,
        "sells_h1": 50,
        "buys_h6": 400,
        "sells_h6": 280,
        "buys_h24": 1000,
        "sells_h24": 750,
        "price_change_m5": 2.0,
        "price_change_h1": 8.0,
        "price_change_h6": 15.0,
        "price_change_h24": 20.0,
        # Created 12 hours ago
        "pair_created_at": int((time.time() - 12 * 3600) * 1000),
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
        assert filter_token(_make_token(liquidity_usd=5_000)) is False

    def test_rejects_low_mcap(self):
        assert filter_token(_make_token(market_cap=20_000)) is False

    def test_rejects_high_mcap(self):
        assert filter_token(_make_token(market_cap=10_000_000)) is False

    def test_rejects_too_new(self):
        # 5 minutes old — under the 10 min minimum
        ts = int((time.time() - 5 * 60) * 1000)
        assert filter_token(_make_token(pair_created_at=ts)) is False

    def test_passes_10_min_old(self):
        ts = int((time.time() - 15 * 60) * 1000)
        assert filter_token(_make_token(pair_created_at=ts)) is True

    def test_rejects_old_token(self):
        old_ts = int((time.time() - 200 * 3600) * 1000)
        assert filter_token(_make_token(pair_created_at=old_ts)) is False

    def test_rejects_low_txns(self):
        assert filter_token(_make_token(buys_h1=2, sells_h1=3)) is False

    def test_custom_thresholds(self):
        token = _make_token(liquidity_usd=5_000, market_cap=30_000)
        assert filter_token(
            token, min_liquidity=1_000, min_market_cap=10_000
        ) is True


# ── Score tests ──────────────────────────────────────────────────


class TestScoreToken:
    def test_returns_all_fields(self):
        result = score_token(_make_token())
        assert "score" in result
        assert "components" in result
        assert "penalty" in result
        assert "buy_ratio_h1" in result
        assert "buy_ratio_h6" in result
        assert "buy_ratio_h24" in result
        assert "vol_build_ratio" in result
        comp = result["components"]
        assert "buy_pressure" in comp
        assert "volume_trend" in comp
        assert "price_quality" in comp
        assert "mcap_fit" in comp
        assert "boost" in comp

    def test_score_nonnegative(self):
        result = score_token(_make_token())
        assert result["score"] >= 0

    def test_strong_buy_pressure_scores_higher(self):
        weak = score_token(_make_token(
            buys_h1=50, sells_h1=80, buys_h6=200, sells_h6=300,
            buys_h24=600, sells_h24=900,
        ))
        strong = score_token(_make_token(
            buys_h1=90, sells_h1=30, buys_h6=400, sells_h6=150,
            buys_h24=1200, sells_h24=400,
        ))
        assert strong["score"] > weak["score"]
        assert strong["components"]["buy_pressure"] > weak["components"]["buy_pressure"]

    def test_consistency_bonus(self):
        # All timeframes >55% buys
        consistent = score_token(_make_token(
            buys_h1=70, sells_h1=50, buys_h6=350, sells_h6=250,
            buys_h24=900, sells_h24=650,
        ))
        # Only h1 is >55%
        inconsistent = score_token(_make_token(
            buys_h1=70, sells_h1=50, buys_h6=280, sells_h6=320,
            buys_h24=750, sells_h24=800,
        ))
        assert consistent["components"]["buy_pressure"] > inconsistent["components"]["buy_pressure"]

    def test_mcap_sweet_spot(self):
        sweet = score_token(_make_token(market_cap=150_000))  # in sweet spot
        too_big = score_token(_make_token(market_cap=4_000_000))
        assert sweet["components"]["mcap_fit"] > too_big["components"]["mcap_fit"]
        assert sweet["components"]["mcap_fit"] == 15  # max score

    def test_mcap_peak_range(self):
        low = score_token(_make_token(market_cap=50_000))
        mid = score_token(_make_token(market_cap=150_000))
        high = score_token(_make_token(market_cap=3_000_000))
        assert mid["components"]["mcap_fit"] >= low["components"]["mcap_fit"]
        assert mid["components"]["mcap_fit"] >= high["components"]["mcap_fit"]

    def test_boost_increases_score(self):
        no_boost = score_token(_make_token(boost_active=0))
        boosted = score_token(_make_token(boost_active=5))
        assert boosted["score"] > no_boost["score"]
        assert boosted["components"]["boost"] == 10

    def test_multi_timeframe_green_bonus(self):
        all_green = score_token(_make_token(
            price_change_h1=5, price_change_h6=10, price_change_h24=15,
        ))
        mixed = score_token(_make_token(
            price_change_h1=5, price_change_h6=-3, price_change_h24=15,
        ))
        assert all_green["components"]["price_quality"] > mixed["components"]["price_quality"]

    def test_sell_pressure_penalty(self):
        normal = score_token(_make_token(buys_m5=12, sells_m5=8))
        dumping = score_token(_make_token(buys_m5=2, sells_m5=15))
        assert dumping["penalty"] > normal["penalty"]
        assert dumping["score"] < normal["score"]

    def test_price_crash_penalty(self):
        stable = score_token(_make_token(price_change_h1=5))
        crashed = score_token(_make_token(price_change_h1=-35))
        assert crashed["penalty"] > stable["penalty"]

    def test_extreme_volatility_penalty(self):
        calm = score_token(_make_token(price_change_m5=3))
        volatile = score_token(_make_token(price_change_m5=25))
        assert volatile["penalty"] > calm["penalty"]

    def test_volume_spike_penalty(self):
        # vol_h1 way above vol_h6 average = suspicious spike
        organic = score_token(_make_token(volume_h1=15_000, volume_h6=60_000))
        spike = score_token(_make_token(volume_h1=100_000, volume_h6=60_000))
        assert spike["penalty"] > organic["penalty"]

    def test_zero_volume_doesnt_crash(self):
        result = score_token(_make_token(
            volume_m5=0, volume_h1=0, volume_h6=0, volume_h24=0,
            buys_m5=0, sells_m5=0, buys_h1=5, sells_h1=6,
        ))
        assert result["score"] >= 0

    def test_buy_ratios_calculated(self):
        result = score_token(_make_token(buys_h1=80, sells_h1=20))
        assert abs(result["buy_ratio_h1"] - 0.80) < 0.01


# ── Rank tests ───────────────────────────────────────────────────


class TestScoreAndRank:
    def test_sorts_by_score_desc(self):
        tokens = [
            _make_token(address="a", buys_h1=50, sells_h1=80),  # weak
            _make_token(address="b", buys_h1=90, sells_h1=30),  # strong
            _make_token(address="c", buys_h1=70, sells_h1=50),  # medium
        ]
        ranked = score_and_rank(tokens)
        scores = [t["score"] for t in ranked]
        assert scores == sorted(scores, reverse=True)
        assert ranked[0]["address"] == "b"

    def test_filters_applied(self):
        tokens = [
            _make_token(address="good", liquidity_usd=25_000, market_cap=150_000),
            _make_token(address="low_liq", liquidity_usd=5_000, market_cap=150_000),
            _make_token(address="low_mcap", liquidity_usd=25_000, market_cap=10_000),
        ]
        ranked = score_and_rank(tokens)
        addrs = [t["address"] for t in ranked]
        assert "good" in addrs
        assert "low_liq" not in addrs
        assert "low_mcap" not in addrs

    def test_empty_input(self):
        assert score_and_rank([]) == []

    def test_merges_score_into_token(self):
        tokens = [_make_token()]
        ranked = score_and_rank(tokens)
        assert len(ranked) == 1
        t = ranked[0]
        assert "address" in t
        assert "symbol" in t
        assert "score" in t
        assert "components" in t
        assert "penalty" in t
