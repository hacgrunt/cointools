"""Tests for scout.aggregator module."""

from cointools.scout.aggregator import TokenSignal, build_token_feed


def _agg(mint, unique_buyers=1, unique_sellers=0, buy_count=1, sell_count=0,
         sol_in=1.0, sol_out=0.0, first=1000, last=2000):
    return {
        "token_mint": mint,
        "unique_buyers": unique_buyers,
        "unique_sellers": unique_sellers,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_sol_in": sol_in,
        "total_sol_out": sol_out,
        "first_seen": first,
        "last_seen": last,
    }


def _meta(mint, name="Test", symbol="TST", price=0.01, mcap=100000,
          liq=5000, vol=10000):
    return {
        mint: {
            "name": name,
            "symbol": symbol,
            "price_usd": price,
            "market_cap": mcap,
            "liquidity_usd": liq,
            "volume_24h": vol,
            "pair_url": "https://dex.example",
            "dex": "raydium",
        }
    }


def _trade(wallet, mint, ttype):
    return {"wallet_address": wallet, "token_mint": mint, "trade_type": ttype}


class TestBuildTokenFeed:
    def test_basic_feed(self):
        agg = [_agg("TOKEN_A", unique_buyers=2, sol_in=5.0)]
        meta = _meta("TOKEN_A")
        labels = {"W1": "whale", "W2": "degen"}
        trades = [_trade("W1", "TOKEN_A", "BUY"), _trade("W2", "TOKEN_A", "BUY")]

        feed = build_token_feed(agg, meta, labels, trades)
        assert len(feed) == 1
        assert feed[0].symbol == "TST"
        assert feed[0].unique_buyers == 2
        assert set(feed[0].buyer_labels) == {"whale", "degen"}

    def test_filters_low_liquidity(self):
        agg = [_agg("TOKEN_A")]
        meta = {"TOKEN_A": {
            "name": "LowLiq", "symbol": "LL", "price_usd": 0.001,
            "market_cap": 100, "liquidity_usd": 500,  # Below $1K threshold
            "volume_24h": 10, "pair_url": "", "dex": "",
        }}
        feed = build_token_feed(agg, meta, {}, [])
        assert len(feed) == 0

    def test_keeps_unknown_tokens(self):
        """Tokens without metadata should still appear (no liquidity data to filter on)."""
        agg = [_agg("UNKNOWN_TOKEN", unique_buyers=3, sol_in=10.0)]
        feed = build_token_feed(agg, {}, {}, [])
        assert len(feed) == 1
        assert feed[0].name == "Unknown"

    def test_ranking_by_conviction(self):
        agg = [
            _agg("TOKEN_A", unique_buyers=1, sol_in=1.0),
            _agg("TOKEN_B", unique_buyers=3, sol_in=10.0),
            _agg("TOKEN_C", unique_buyers=2, sol_in=5.0),
        ]
        meta = {**_meta("TOKEN_A"), **_meta("TOKEN_B", symbol="B"), **_meta("TOKEN_C", symbol="C")}
        feed = build_token_feed(agg, meta, {}, [])
        # TOKEN_B should rank first (3 buyers, 10 SOL)
        assert feed[0].token_mint == "TOKEN_B"
        assert feed[1].token_mint == "TOKEN_C"
        assert feed[2].token_mint == "TOKEN_A"

    def test_seller_labels(self):
        agg = [_agg("TOKEN_A", unique_sellers=1, sell_count=1)]
        meta = _meta("TOKEN_A")
        labels = {"W1": "paperhands"}
        trades = [_trade("W1", "TOKEN_A", "SELL")]

        feed = build_token_feed(agg, meta, labels, trades)
        assert feed[0].seller_labels == ["paperhands"]

    def test_net_flow(self):
        agg = [_agg("TOKEN_A", sol_in=10.0, sol_out=3.0)]
        meta = _meta("TOKEN_A")
        feed = build_token_feed(agg, meta, {}, [])
        assert feed[0].net_flow == 7.0

    def test_wallet_label_fallback(self):
        """Wallets without labels should show truncated address."""
        agg = [_agg("TOKEN_A")]
        meta = _meta("TOKEN_A")
        labels = {}
        trades = [_trade("ABCDEFGHIJKLMNOP", "TOKEN_A", "BUY")]

        feed = build_token_feed(agg, meta, labels, trades)
        assert feed[0].buyer_labels == ["ABCDEFGH.."]


class TestTokenSignal:
    def test_conviction_score(self):
        sig = TokenSignal(
            token_mint="X", name="X", symbol="X", price_usd=0, market_cap=0,
            liquidity_usd=0, volume_24h=0, pair_url="", dex="",
            unique_buyers=3, unique_sellers=0, buy_count=5, sell_count=0,
            total_sol_in=20.0, total_sol_out=0.0, first_seen=0, last_seen=0,
        )
        # 3*10 + min(20, 100) + 5 = 55
        assert sig.conviction_score == 55.0

    def test_net_flow_property(self):
        sig = TokenSignal(
            token_mint="X", name="X", symbol="X", price_usd=0, market_cap=0,
            liquidity_usd=0, volume_24h=0, pair_url="", dex="",
            unique_buyers=1, unique_sellers=1, buy_count=1, sell_count=1,
            total_sol_in=10.0, total_sol_out=3.0, first_seen=0, last_seen=0,
        )
        assert sig.net_flow == 7.0
