"""Aggregate trades into a ranked token feed."""

from __future__ import annotations

from dataclasses import dataclass, field

from cointools.scout.filters import MIN_LIQUIDITY_USD


@dataclass
class TokenSignal:
    """A token surfaced by scout, ranked by smart-wallet conviction."""

    token_mint: str
    name: str
    symbol: str
    price_usd: float
    market_cap: float
    liquidity_usd: float
    volume_24h: float
    pair_url: str
    dex: str

    unique_buyers: int
    unique_sellers: int
    buy_count: int
    sell_count: int
    total_sol_in: float
    total_sol_out: float
    first_seen: int
    last_seen: int

    buyer_labels: list[str] = field(default_factory=list)
    seller_labels: list[str] = field(default_factory=list)

    @property
    def net_flow(self) -> float:
        return self.total_sol_in - self.total_sol_out

    @property
    def conviction_score(self) -> float:
        """Higher = more wallets buying with more volume and net-positive flow."""
        buyer_weight = self.unique_buyers * 10
        volume_weight = min(self.total_sol_in, 100)  # cap contribution
        net_bonus = 5 if self.net_flow > 0 else -5
        return buyer_weight + volume_weight + net_bonus


def build_token_feed(
    aggregated_trades: list[dict],
    token_metadata: dict[str, dict],
    wallet_labels: dict[str, str],
    trade_details: list[dict],
) -> list[TokenSignal]:
    """Build a ranked feed of token signals.

    Parameters
    ----------
    aggregated_trades:
        Output of ``db.get_token_aggregation()``.
    token_metadata:
        Output of ``tokens.fetch_token_metadata()`` — mint → metadata.
    wallet_labels:
        Mapping of wallet address → human label.
    trade_details:
        Raw trade rows for resolving buyer/seller labels per token.
    """
    # Collect buyer/seller labels per token
    token_buyers: dict[str, set[str]] = {}
    token_sellers: dict[str, set[str]] = {}
    for trade in trade_details:
        mint = trade["token_mint"]
        addr = trade["wallet_address"]
        label = wallet_labels.get(addr, addr[:8] + "..")
        if trade["trade_type"] == "BUY":
            token_buyers.setdefault(mint, set()).add(label)
        else:
            token_sellers.setdefault(mint, set()).add(label)

    signals: list[TokenSignal] = []
    for agg in aggregated_trades:
        mint = agg["token_mint"]
        meta = token_metadata.get(mint, {})

        liquidity = meta.get("liquidity_usd", 0)
        # Skip tokens with known-low liquidity, but keep unknowns (no meta)
        if meta and liquidity < MIN_LIQUIDITY_USD:
            continue

        signals.append(
            TokenSignal(
                token_mint=mint,
                name=meta.get("name", "Unknown"),
                symbol=meta.get("symbol", mint[:8] + ".."),
                price_usd=meta.get("price_usd", 0),
                market_cap=meta.get("market_cap", 0),
                liquidity_usd=liquidity,
                volume_24h=meta.get("volume_24h", 0),
                pair_url=meta.get("pair_url", ""),
                dex=meta.get("dex", ""),
                unique_buyers=agg["unique_buyers"],
                unique_sellers=agg["unique_sellers"],
                buy_count=agg["buy_count"],
                sell_count=agg["sell_count"],
                total_sol_in=agg["total_sol_in"],
                total_sol_out=agg["total_sol_out"],
                first_seen=agg["first_seen"],
                last_seen=agg["last_seen"],
                buyer_labels=sorted(token_buyers.get(mint, set())),
                seller_labels=sorted(token_sellers.get(mint, set())),
            )
        )

    signals.sort(key=lambda s: s.conviction_score, reverse=True)
    return signals
