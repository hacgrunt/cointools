"""Attention acceleration scoring engine.

Computes a score for each token based on how much attention is
accelerating RIGHT NOW compared to recent averages.  The key insight:
DexScreener provides volume/txn data in 5m, 1h, 6h, 24h windows.
By comparing the short-term rate to the longer-term average, we can
detect acceleration from a single snapshot.
"""

from __future__ import annotations

import time

# ── Filter thresholds ────────────────────────────────────────────────

DEFAULT_MIN_LIQUIDITY = 1_000  # $1K minimum liquidity
DEFAULT_MAX_MARKET_CAP = 50_000_000  # $50M max market cap
DEFAULT_MAX_AGE_HOURS = 72  # 3 days
DEFAULT_MIN_TXNS_5M = 1  # at least 1 transaction in last 5 min


def filter_token(
    token: dict,
    *,
    min_liquidity: float = DEFAULT_MIN_LIQUIDITY,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    min_txns_5m: int = DEFAULT_MIN_TXNS_5M,
) -> bool:
    """Return True if the token passes all filters."""
    liq = token.get("liquidity_usd", 0)
    mcap = token.get("market_cap", 0)
    txns_5m = token.get("buys_m5", 0) + token.get("sells_m5", 0)
    created = token.get("pair_created_at", 0)

    if liq < min_liquidity:
        return False
    if mcap > max_market_cap and mcap > 0:
        return False
    if txns_5m < min_txns_5m:
        return False

    if created > 0:
        age_hours = (time.time() * 1000 - created) / 3_600_000
        if age_hours > max_age_hours:
            return False

    return True


# ── Scoring ──────────────────────────────────────────────────────────


def _safe_ratio(short: float, long_avg: float) -> float:
    """Compute short / long_avg, handling zero denominators."""
    if long_avg > 0:
        return short / long_avg
    return 2.0 if short > 0 else 0.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score_token(token: dict) -> dict:
    """Compute the attention acceleration score for a token.

    Returns a dict with score, component breakdown, and derived metrics.
    The score is unbounded but typically 0-150 for most tokens.

    Components (max raw contribution before age factor):
      - volume_accel  (0-30): 5m volume rate vs 1h average
      - txn_accel     (0-25): 5m transaction rate vs 1h average
      - boost         (0-20): DexScreener boost signal
      - momentum      (0-15): 5m price change
      - vol_liq       (0-10): volume relative to liquidity depth
    """
    vol_m5 = token.get("volume_m5", 0)
    vol_h1 = token.get("volume_h1", 0)
    vol_h6 = token.get("volume_h6", 0)

    buys_m5 = token.get("buys_m5", 0)
    sells_m5 = token.get("sells_m5", 0)
    buys_h1 = token.get("buys_h1", 0)
    sells_h1 = token.get("sells_h1", 0)
    txn_m5 = buys_m5 + sells_m5
    txn_h1 = buys_h1 + sells_h1

    price_m5 = token.get("price_change_m5", 0)
    liq = token.get("liquidity_usd", 0)
    boost_active = token.get("boost_active", 0)
    created = token.get("pair_created_at", 0)

    # ── 1. Volume Acceleration (0-30 pts) ────────────────────────
    # Compare current 5m volume to the hourly average 5m volume
    vol_h1_avg_5m = vol_h1 / 12 if vol_h1 > 0 else 0
    vol_ratio = _safe_ratio(vol_m5, vol_h1_avg_5m)
    # ratio=1 means average, >1 means accelerating
    vol_score = _clamp((vol_ratio - 0.5) * 15, 0, 30)

    # ── 2. Transaction Acceleration (0-25 pts) ───────────────────
    txn_h1_avg_5m = txn_h1 / 12 if txn_h1 > 0 else 0
    txn_ratio = _safe_ratio(txn_m5, txn_h1_avg_5m)
    txn_score = _clamp((txn_ratio - 0.5) * 12.5, 0, 25)

    # ── 3. Boost Signal (0-20 pts) ───────────────────────────────
    # Each active boost = 4 points, capped at 20
    boost_score = _clamp(boost_active * 4, 0, 20)

    # ── 4. Price Momentum (0-15 pts) ─────────────────────────────
    # 5m price change as a signal (positive movement = attention)
    momentum_score = _clamp(price_m5 * 1.5, 0, 15)

    # ── 5. Volume / Liquidity Ratio (0-10 pts) ───────────────────
    # How much volume relative to pool depth — high ratio = intense trading
    if liq > 0:
        vol_liq_pct = (vol_m5 / liq) * 100
    else:
        vol_liq_pct = 0
    vlr_score = _clamp(vol_liq_pct * 5, 0, 10)

    # ── Raw score ────────────────────────────────────────────────
    raw = vol_score + txn_score + boost_score + momentum_score + vlr_score

    # ── Age factor (multiplier) ──────────────────────────────────
    if created > 0:
        age_hours = max(0, (time.time() * 1000 - created) / 3_600_000)
    else:
        age_hours = 999

    if age_hours <= 1:
        age_factor = 2.0
    elif age_hours <= 6:
        age_factor = 1.5
    elif age_hours <= 24:
        age_factor = 1.2
    elif age_hours <= 48:
        age_factor = 1.0
    else:
        age_factor = max(0.5, 1.0 - (age_hours - 48) / 336)

    final_score = raw * age_factor

    return {
        "score": round(final_score, 1),
        "components": {
            "volume_accel": round(vol_score, 1),
            "txn_accel": round(txn_score, 1),
            "boost": round(boost_score, 1),
            "momentum": round(momentum_score, 1),
            "vol_liq": round(vlr_score, 1),
        },
        "age_factor": round(age_factor, 2),
        "age_hours": round(age_hours, 1),
        "vol_ratio": round(vol_ratio, 2),
        "txn_ratio": round(txn_ratio, 2),
        "buy_pressure": round(buys_m5 / max(txn_m5, 1), 2),
    }


def score_and_rank(
    tokens: list[dict],
    *,
    min_liquidity: float = DEFAULT_MIN_LIQUIDITY,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> list[dict]:
    """Filter, score, and rank a list of token snapshots.

    Returns tokens sorted by attention score (descending), each
    augmented with scoring metadata.
    """
    scored: list[dict] = []

    for token in tokens:
        if not filter_token(
            token,
            min_liquidity=min_liquidity,
            max_market_cap=max_market_cap,
            max_age_hours=max_age_hours,
        ):
            continue

        result = score_token(token)
        # Merge score data into the token dict
        enriched = {**token, **result}
        scored.append(enriched)

    scored.sort(key=lambda t: t["score"], reverse=True)
    return scored
