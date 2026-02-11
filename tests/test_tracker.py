"""Tests for tracker module: signal classification and sentiment."""

from cointools.tracker import (
    AnalysisReport,
    HolderAnalysis,
    Sentiment,
    Signal,
    build_report,
    classify_holders,
    compute_sentiment,
)


def _holder(rank, current, historical=None):
    return {
        "rank": rank,
        "holder_address": f"acc{rank}",
        "owner_address": f"owner{rank}",
        "current_balance": current,
        "historical_balance": historical,
    }


class TestClassifyHolders:
    def test_buy_signal(self):
        results = classify_holders([_holder(1, 1000.0, 500.0)])
        assert results[0].signal == Signal.BUY
        assert results[0].change == 500.0
        assert results[0].change_pct == 100.0

    def test_sell_signal(self):
        results = classify_holders([_holder(1, 300.0, 500.0)])
        assert results[0].signal == Signal.SELL
        assert results[0].change == -200.0

    def test_hold_signal(self):
        results = classify_holders([_holder(1, 1000.0, 1000.0)])
        assert results[0].signal == Signal.HOLD
        assert results[0].change == 0.0

    def test_new_signal_when_no_history(self):
        results = classify_holders([_holder(1, 1000.0, None)])
        assert results[0].signal == Signal.NEW
        assert results[0].change is None

    def test_change_pct_from_zero(self):
        results = classify_holders([_holder(1, 100.0, 0.0)])
        assert results[0].signal == Signal.BUY
        assert results[0].change_pct is None  # division by zero → None

    def test_multiple_holders(self):
        data = [
            _holder(1, 1000.0, 500.0),
            _holder(2, 300.0, 600.0),
            _holder(3, 100.0, 100.0),
        ]
        results = classify_holders(data)
        assert [r.signal for r in results] == [Signal.BUY, Signal.SELL, Signal.HOLD]


class TestComputeSentiment:
    def test_accumulation(self):
        holders = [
            HolderAnalysis(1, "a", "o", 100, 50, 50, 100, Signal.BUY),
            HolderAnalysis(2, "b", "o", 100, 50, 50, 100, Signal.BUY),
            HolderAnalysis(3, "c", "o", 100, 200, -100, -50, Signal.SELL),
        ]
        assert compute_sentiment(holders) == Sentiment.ACCUMULATION

    def test_distribution(self):
        holders = [
            HolderAnalysis(1, "a", "o", 100, 200, -100, -50, Signal.SELL),
            HolderAnalysis(2, "b", "o", 100, 200, -100, -50, Signal.SELL),
            HolderAnalysis(3, "c", "o", 100, 50, 50, 100, Signal.BUY),
        ]
        assert compute_sentiment(holders) == Sentiment.DISTRIBUTION

    def test_neutral(self):
        holders = [
            HolderAnalysis(1, "a", "o", 100, 50, 50, 100, Signal.BUY),
            HolderAnalysis(2, "b", "o", 100, 200, -100, -50, Signal.SELL),
        ]
        assert compute_sentiment(holders) == Sentiment.NEUTRAL


class TestBuildReport:
    def test_report_structure(self):
        data = [
            _holder(1, 1000.0, 500.0),
            _holder(2, 300.0, 600.0),
            _holder(3, 100.0, 100.0),
            _holder(4, 50.0, None),
        ]
        report = build_report("mintABC", "7d", data)
        assert isinstance(report, AnalysisReport)
        assert report.mint == "mintABC"
        assert report.period == "7d"
        assert report.buying == 1
        assert report.selling == 1
        assert report.holding == 1
        assert report.unknown == 1
        assert report.sentiment == Sentiment.NEUTRAL
        assert len(report.holders) == 4
