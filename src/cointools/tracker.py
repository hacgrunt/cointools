"""Core analysis logic: classify signals and compute aggregate sentiment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NEW = "NEW"          # appeared in top 20 (no historical data / account didn't exist)
    UNKNOWN = "UNKNOWN"  # couldn't determine historical balance


@dataclass
class HolderAnalysis:
    rank: int
    holder_address: str
    owner_address: str | None
    current_balance: float
    historical_balance: float | None
    change: float | None
    change_pct: float | None
    signal: Signal


class Sentiment(Enum):
    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"
    NEUTRAL = "NEUTRAL"


@dataclass
class AnalysisReport:
    mint: str
    period: str
    holders: list[HolderAnalysis]
    buying: int
    selling: int
    holding: int
    unknown: int
    sentiment: Sentiment


def classify_holders(holders_data: list[dict]) -> list[HolderAnalysis]:
    """Classify each holder as BUY/SELL/HOLD/NEW based on balance delta."""
    results = []
    for h in holders_data:
        current = h["current_balance"]
        historical = h.get("historical_balance")

        if historical is None:
            results.append(
                HolderAnalysis(
                    rank=h["rank"],
                    holder_address=h["holder_address"],
                    owner_address=h.get("owner_address"),
                    current_balance=current,
                    historical_balance=None,
                    change=None,
                    change_pct=None,
                    signal=Signal.NEW,
                )
            )
            continue

        change = current - historical
        # Use a small epsilon relative to current balance to avoid float noise
        epsilon = max(current, historical, 1.0) * 1e-9

        if abs(change) < epsilon:
            signal = Signal.HOLD
            change = 0.0
        elif change > 0:
            signal = Signal.BUY
        else:
            signal = Signal.SELL

        change_pct = (change / historical * 100) if historical != 0 else None

        results.append(
            HolderAnalysis(
                rank=h["rank"],
                holder_address=h["holder_address"],
                owner_address=h.get("owner_address"),
                current_balance=current,
                historical_balance=historical,
                change=change,
                change_pct=change_pct,
                signal=signal,
            )
        )
    return results


def compute_sentiment(holders: list[HolderAnalysis]) -> Sentiment:
    buying = sum(1 for h in holders if h.signal == Signal.BUY)
    selling = sum(1 for h in holders if h.signal == Signal.SELL)

    if buying > selling:
        return Sentiment.ACCUMULATION
    elif selling > buying:
        return Sentiment.DISTRIBUTION
    return Sentiment.NEUTRAL


def build_report(
    mint: str, period: str, holders_data: list[dict]
) -> AnalysisReport:
    holders = classify_holders(holders_data)
    sentiment = compute_sentiment(holders)

    return AnalysisReport(
        mint=mint,
        period=period,
        holders=holders,
        buying=sum(1 for h in holders if h.signal == Signal.BUY),
        selling=sum(1 for h in holders if h.signal == Signal.SELL),
        holding=sum(1 for h in holders if h.signal == Signal.HOLD),
        unknown=sum(1 for h in holders if h.signal in (Signal.NEW, Signal.UNKNOWN)),
        sentiment=sentiment,
    )
