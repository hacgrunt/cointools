"""Dual-mode scoring engine: Momentum + Accumulation.

Two complementary scanners that run simultaneously:

**Momentum** — Surfaces tokens where attention is spiking *right now*.
Compares 5-minute rates against hourly averages.  Loose filters,
favours new tokens with accelerating activity.  Good for catching
runners early, but noisier.

**Accumulation** — Finds tokens in the $50K–$5M MCap range showing
organic buying across multiple timeframes, building volume, and
price holding.  Tighter filters, designed to spot breakout candidates
before they move.  Less noise, higher conviction.

DexScreener provides volume/txn data in 5m, 1h, 6h, 24h windows.
Both modes exploit rate-of-change from single snapshots.
"""

from __future__ import annotations

import time

# ── Accumulation filter thresholds ────────────────────────────────────

DEFAULT_MIN_LIQUIDITY = 10_000  # $10K minimum liquidity
DEFAULT_MIN_MARKET_CAP = 50_000  # $50K minimum market cap
DEFAULT_MAX_MARKET_CAP = 5_000_000  # $5M max market cap
DEFAULT_MIN_AGE_MINUTES = 10  # at least 10 min old
DEFAULT_MAX_AGE_HOURS = 168  # 7 days
DEFAULT_MIN_TXNS_H1 = 10  # at least 10 trades in last hour

# ── Momentum filter thresholds ───────────────────────────────────────

MOMENTUM_MIN_LIQUIDITY = 1_000  # $1K — loose
MOMENTUM_MAX_MARKET_CAP = 50_000_000  # $50M
MOMENTUM_MAX_AGE_HOURS = 72  # 3 days
MOMENTUM_MIN_TXNS_M5 = 1  # at least 1 trade in 5 min


def filter_token(
    token: dict,
    *,
    min_liquidity: float = DEFAULT_MIN_LIQUIDITY,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP,
    min_age_minutes: float = DEFAULT_MIN_AGE_MINUTES,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    min_txns_h1: int = DEFAULT_MIN_TXNS_H1,
) -> bool:
    """Return True if the token passes all filters."""
    liq = token.get("liquidity_usd", 0)
    mcap = token.get("market_cap", 0)
    txns_h1 = (token.get("buys_h1", 0) + token.get("sells_h1", 0))
    created = token.get("pair_created_at", 0)

    if liq < min_liquidity:
        return False
    if mcap < min_market_cap and mcap > 0:
        return False
    if mcap > max_market_cap and mcap > 0:
        return False
    if txns_h1 < min_txns_h1:
        return False

    if created > 0:
        age_minutes = (time.time() * 1000 - created) / 60_000
        if age_minutes < min_age_minutes:
            return False
        age_hours = age_minutes / 60
        if age_hours > max_age_hours:
            return False

    return True


# ── Scoring ──────────────────────────────────────────────────────────


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _buy_ratio(buys: int, sells: int) -> float:
    """Buy ratio: 0.0 (all sells) to 1.0 (all buys). 0.5 = neutral."""
    total = buys + sells
    if total == 0:
        return 0.5
    return buys / total


def score_token(token: dict) -> dict:
    """Compute the accumulation score for a token.

    Returns a dict with score, component breakdown, and derived metrics.
    Score typically ranges 0-100.

    Components:
      - buy_pressure  (0-30): sustained buying across h1, h6, h24
      - volume_trend  (0-25): volume building over time (not spiking)
      - price_quality (0-20): steady multi-timeframe price strength
      - mcap_fit      (0-15): how well MCap fits the $50K-$500K sweet spot
      - boost         (0-10): DexScreener paid promotion signal
    """
    buys_m5 = token.get("buys_m5", 0)
    sells_m5 = token.get("sells_m5", 0)
    buys_h1 = token.get("buys_h1", 0)
    sells_h1 = token.get("sells_h1", 0)
    buys_h6 = token.get("buys_h6", 0)
    sells_h6 = token.get("sells_h6", 0)
    buys_h24 = token.get("buys_h24", 0)
    sells_h24 = token.get("sells_h24", 0)

    vol_m5 = token.get("volume_m5", 0)
    vol_h1 = token.get("volume_h1", 0)
    vol_h6 = token.get("volume_h6", 0)
    vol_h24 = token.get("volume_h24", 0)

    price_m5 = token.get("price_change_m5", 0)
    price_h1 = token.get("price_change_h1", 0)
    price_h6 = token.get("price_change_h6", 0)
    price_h24 = token.get("price_change_h24", 0)

    liq = token.get("liquidity_usd", 0)
    mcap = token.get("market_cap", 0)
    boost_active = token.get("boost_active", 0)
    created = token.get("pair_created_at", 0)

    txn_m5 = buys_m5 + sells_m5

    # ── 1. Multi-Timeframe Buy Pressure (0-30 pts) ──────────────
    # The core signal: are buyers dominant across all timeframes?
    br_h1 = _buy_ratio(buys_h1, sells_h1)
    br_h6 = _buy_ratio(buys_h6, sells_h6)
    br_h24 = _buy_ratio(buys_h24, sells_h24)

    # Points for each timeframe (max 8 each = 24 base)
    # 0.5 = neutral (0 pts), 0.6 = mild buying (4 pts), 0.7+ = strong (8 pts)
    h1_pts = _clamp((br_h1 - 0.5) * 40, 0, 8)
    h6_pts = _clamp((br_h6 - 0.5) * 40, 0, 8)
    h24_pts = _clamp((br_h24 - 0.5) * 40, 0, 8)

    # Consistency bonus: if all three are >55% buys, extra 6 pts
    consistency_bonus = 0
    if br_h1 > 0.55 and br_h6 > 0.55 and br_h24 > 0.55:
        consistency_bonus = 6

    buy_pressure_score = _clamp(h1_pts + h6_pts + h24_pts + consistency_bonus, 0, 30)

    # ── 2. Volume Trend (0-25 pts) ──────────────────────────────
    # Is volume building organically? Compare rates across windows.
    # We want gradual increase, NOT explosive spikes.
    vol_h1_rate = vol_h1  # per hour
    vol_h6_rate = vol_h6 / 6 if vol_h6 > 0 else 0  # per hour avg
    vol_h24_rate = vol_h24 / 24 if vol_h24 > 0 else 0  # per hour avg

    # Recent volume above 6h average = building (10 pts max)
    if vol_h6_rate > 0:
        vol_build_ratio = vol_h1_rate / vol_h6_rate
    else:
        vol_build_ratio = 1.5 if vol_h1_rate > 0 else 0

    # Sweet spot: 1.2-3x = building. >5x = likely spike (penalized later)
    vol_build_pts = _clamp((vol_build_ratio - 0.8) * 8, 0, 12)

    # 6h volume above 24h average = sustained trend (8 pts max)
    if vol_h24_rate > 0:
        vol_trend_ratio = vol_h6_rate / vol_h24_rate
    else:
        vol_trend_ratio = 1.5 if vol_h6_rate > 0 else 0
    vol_trend_pts = _clamp((vol_trend_ratio - 0.8) * 8, 0, 8)

    # Minimum activity: need some base volume (5 pts)
    vol_base_pts = _clamp(vol_h1 / 2000, 0, 5)  # $2K/hr = 5 pts

    volume_trend_score = _clamp(vol_build_pts + vol_trend_pts + vol_base_pts, 0, 25)

    # ── 3. Price Momentum Quality (0-20 pts) ────────────────────
    # Steady green across timeframes = accumulation.
    # Wild swings or crashes = dump.
    # Points for positive price across each window (max 5 each = 15)
    p_h1_pts = _clamp(price_h1 * 0.5, 0, 5) if price_h1 > 0 else 0
    p_h6_pts = _clamp(price_h6 * 0.25, 0, 5) if price_h6 > 0 else 0
    p_h24_pts = _clamp(price_h24 * 0.15, 0, 5) if price_h24 > 0 else 0

    # Multi-timeframe green bonus: all positive = extra 5 pts
    green_bonus = 0
    if price_h1 > 0 and price_h6 > 0 and price_h24 > 0:
        green_bonus = 5

    price_quality_score = _clamp(
        p_h1_pts + p_h6_pts + p_h24_pts + green_bonus, 0, 20
    )

    # ── 4. MCap Sweet Spot (0-15 pts) ───────────────────────────
    # Peak score in the $50K-$200K range, fades outside.
    if mcap <= 0:
        mcap_score = 0
    elif mcap < 50_000:
        mcap_score = (mcap / 50_000) * 5  # ramp up to $50K
    elif mcap <= 200_000:
        mcap_score = 15  # sweet spot: full points
    elif mcap <= 500_000:
        mcap_score = 15 - ((mcap - 200_000) / 300_000) * 5  # 15→10
    elif mcap <= 2_000_000:
        mcap_score = 10 - ((mcap - 500_000) / 1_500_000) * 5  # 10→5
    elif mcap <= 5_000_000:
        mcap_score = 5 - ((mcap - 2_000_000) / 3_000_000) * 5  # 5→0
    else:
        mcap_score = 0
    mcap_score = _clamp(mcap_score, 0, 15)

    # ── 5. Boost Signal (0-10 pts) ──────────────────────────────
    boost_score = _clamp(boost_active * 2, 0, 10)

    # ── Raw score ───────────────────────────────────────────────
    raw = (
        buy_pressure_score
        + volume_trend_score
        + price_quality_score
        + mcap_score
        + boost_score
    )

    # ── Penalties ───────────────────────────────────────────────
    penalty = 0

    # Heavy sell pressure in last 5 min (recent dumping)
    br_m5 = _buy_ratio(buys_m5, sells_m5)
    if txn_m5 >= 3 and br_m5 < 0.3:
        # 70%+ sells in 5m — heavy penalty
        penalty += 20
    elif txn_m5 >= 3 and br_m5 < 0.4:
        penalty += 10

    # Price crash in last hour
    if price_h1 < -30:
        penalty += 15
    elif price_h1 < -15:
        penalty += 8

    # Extreme 5m volatility (pump-and-dump signal)
    if abs(price_m5) > 20:
        penalty += 5

    # Extreme volume spike (wash trading or exit dump)
    if vol_build_ratio > 8:
        penalty += 10
    elif vol_build_ratio > 5:
        penalty += 5

    final_score = max(0, raw - penalty)

    # ── Age ─────────────────────────────────────────────────────
    if created > 0:
        age_hours = max(0, (time.time() * 1000 - created) / 3_600_000)
    else:
        age_hours = 999

    return {
        "score": round(final_score, 1),
        "components": {
            "buy_pressure": round(buy_pressure_score, 1),
            "volume_trend": round(volume_trend_score, 1),
            "price_quality": round(price_quality_score, 1),
            "mcap_fit": round(mcap_score, 1),
            "boost": round(boost_score, 1),
        },
        "penalty": round(penalty, 1),
        "age_hours": round(age_hours, 1),
        "buy_ratio_h1": round(br_h1, 2),
        "buy_ratio_h6": round(br_h6, 2),
        "buy_ratio_h24": round(br_h24, 2),
        "buy_ratio_m5": round(br_m5, 2),
        "vol_build_ratio": round(vol_build_ratio, 2),
        "vol_trend_ratio": round(vol_trend_ratio, 2),
    }


def score_and_rank(
    tokens: list[dict],
    *,
    min_liquidity: float = DEFAULT_MIN_LIQUIDITY,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> list[dict]:
    """Filter, score, and rank a list of token snapshots.

    Returns tokens sorted by accumulation score (descending), each
    augmented with scoring metadata.
    """
    scored: list[dict] = []

    for token in tokens:
        if not filter_token(
            token,
            min_liquidity=min_liquidity,
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
            max_age_hours=max_age_hours,
        ):
            continue

        result = score_token(token)
        enriched = {**token, **result}
        scored.append(enriched)

    scored.sort(key=lambda t: t["score"], reverse=True)
    return scored


# =====================================================================
# MOMENTUM MODE — attention acceleration scoring
# =====================================================================


def filter_token_momentum(
    token: dict,
    *,
    min_liquidity: float = MOMENTUM_MIN_LIQUIDITY,
    max_market_cap: float = MOMENTUM_MAX_MARKET_CAP,
    max_age_hours: float = MOMENTUM_MAX_AGE_HOURS,
    min_txns_m5: int = MOMENTUM_MIN_TXNS_M5,
) -> bool:
    """Return True if the token passes momentum filters (loose)."""
    liq = token.get("liquidity_usd", 0)
    mcap = token.get("market_cap", 0)
    txns_m5 = token.get("buys_m5", 0) + token.get("sells_m5", 0)
    created = token.get("pair_created_at", 0)

    if liq < min_liquidity:
        return False
    if mcap > max_market_cap and mcap > 0:
        return False
    if txns_m5 < min_txns_m5:
        return False

    if created > 0:
        age_hours = (time.time() * 1000 - created) / 3_600_000
        if age_hours > max_age_hours:
            return False

    return True


def score_token_momentum(token: dict) -> dict:
    """Compute the momentum / attention-acceleration score.

    Returns a dict with score, component breakdown, and derived metrics.
    Score can exceed 100 for very hot tokens (age multiplier applies).

    Components (before age multiplier):
      - vol_accel    (0-30): 5m volume rate vs 1h average
      - txn_accel    (0-25): 5m txn rate vs 1h average
      - boost        (0-20): DexScreener paid promotion
      - price_momentum (0-15): 5m price change momentum
      - vol_liq      (0-10): volume relative to liquidity (activity density)
    """
    buys_m5 = token.get("buys_m5", 0)
    sells_m5 = token.get("sells_m5", 0)
    buys_h1 = token.get("buys_h1", 0)
    sells_h1 = token.get("sells_h1", 0)

    vol_m5 = token.get("volume_m5", 0)
    vol_h1 = token.get("volume_h1", 0)

    price_m5 = token.get("price_change_m5", 0)

    liq = token.get("liquidity_usd", 0)
    mcap = token.get("market_cap", 0)
    boost_active = token.get("boost_active", 0)
    created = token.get("pair_created_at", 0)

    txn_m5 = buys_m5 + sells_m5
    txn_h1 = buys_h1 + sells_h1

    # ── 1. Volume Acceleration (0-30 pts) ─────────────────────
    # Compare 5m volume rate to the hourly average.
    # If 5m rate >> hourly average, attention is accelerating.
    vol_h1_per_5m = vol_h1 / 12 if vol_h1 > 0 else 0
    if vol_h1_per_5m > 0:
        vol_accel_ratio = vol_m5 / vol_h1_per_5m
    else:
        vol_accel_ratio = 3.0 if vol_m5 > 0 else 0

    # 1x = baseline (0 pts), 2x = moderate (15 pts), 4x+ = full (30 pts)
    vol_accel_score = _clamp((vol_accel_ratio - 1) * 10, 0, 30)

    # ── 2. Transaction Acceleration (0-25 pts) ────────────────
    txn_h1_per_5m = txn_h1 / 12 if txn_h1 > 0 else 0
    if txn_h1_per_5m > 0:
        txn_accel_ratio = txn_m5 / txn_h1_per_5m
    else:
        txn_accel_ratio = 3.0 if txn_m5 > 0 else 0

    txn_accel_score = _clamp((txn_accel_ratio - 1) * 8, 0, 25)

    # ── 3. Boost Signal (0-20 pts) ────────────────────────────
    boost_score = _clamp(boost_active * 4, 0, 20)

    # ── 4. Price Momentum (0-15 pts) ──────────────────────────
    # Positive 5m price change = momentum building
    if price_m5 > 0:
        price_momentum_score = _clamp(price_m5 * 1.5, 0, 15)
    else:
        price_momentum_score = 0

    # ── 5. Volume / Liquidity Ratio (0-10 pts) ────────────────
    # High volume relative to liquidity = high activity density
    if liq > 0:
        vol_liq_ratio = (vol_m5 / liq) * 100
    else:
        vol_liq_ratio = 0
    vol_liq_score = _clamp(vol_liq_ratio * 5, 0, 10)

    # ── Raw score ─────────────────────────────────────────────
    raw = (
        vol_accel_score
        + txn_accel_score
        + boost_score
        + price_momentum_score
        + vol_liq_score
    )

    # ── Age multiplier ────────────────────────────────────────
    # Newer tokens with momentum are more interesting.
    if created > 0:
        age_hours = max(0, (time.time() * 1000 - created) / 3_600_000)
    else:
        age_hours = 999

    if age_hours < 1:
        age_mult = 2.0
    elif age_hours < 6:
        age_mult = 1.5
    elif age_hours < 24:
        age_mult = 1.2
    elif age_hours < 48:
        age_mult = 1.0
    else:
        # Gradual decay for older tokens
        age_mult = max(0.5, 1.0 - (age_hours - 48) / 200)

    final_score = max(0, raw * age_mult)

    return {
        "score": round(final_score, 1),
        "components": {
            "vol_accel": round(vol_accel_score, 1),
            "txn_accel": round(txn_accel_score, 1),
            "boost": round(boost_score, 1),
            "price_momentum": round(price_momentum_score, 1),
            "vol_liq": round(vol_liq_score, 1),
        },
        "age_mult": round(age_mult, 2),
        "age_hours": round(age_hours, 1),
        "vol_accel_ratio": round(vol_accel_ratio, 2),
        "txn_accel_ratio": round(txn_accel_ratio, 2),
        "vol_liq_ratio": round(vol_liq_ratio, 2),
        "buy_ratio_m5": round(_buy_ratio(buys_m5, sells_m5), 2),
    }


def score_and_rank_momentum(
    tokens: list[dict],
    *,
    min_liquidity: float = MOMENTUM_MIN_LIQUIDITY,
    max_market_cap: float = MOMENTUM_MAX_MARKET_CAP,
    max_age_hours: float = MOMENTUM_MAX_AGE_HOURS,
) -> list[dict]:
    """Filter, score, and rank tokens by momentum (attention acceleration).

    Returns tokens sorted by momentum score (descending).
    """
    scored: list[dict] = []

    for token in tokens:
        if not filter_token_momentum(
            token,
            min_liquidity=min_liquidity,
            max_market_cap=max_market_cap,
            max_age_hours=max_age_hours,
        ):
            continue

        result = score_token_momentum(token)
        enriched = {**token, **result}
        scored.append(enriched)

    scored.sort(key=lambda t: t["score"], reverse=True)
    return scored
