"""Rich terminal display for scout output."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.text import Text

from cointools.scout.aggregator import TokenSignal

console = Console()


def _fmt_usd(val: float) -> str:
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:,.1f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:,.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:,.1f}K"
    if val >= 1:
        return f"${val:,.2f}"
    if val > 0:
        return f"${val:.6f}"
    return "$0"


def _fmt_sol(val: float) -> str:
    if val >= 1_000:
        return f"{val:,.0f} SOL"
    if val >= 1:
        return f"{val:,.2f} SOL"
    return f"{val:.4f} SOL"


def _time_ago(ts: int) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    diff = now - ts
    if diff < 0:
        return "just now"
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    return f"{diff // 86400}d ago"


def render_wallet_list(wallets: list[dict]) -> None:
    if not wallets:
        console.print(
            "[dim]No wallets tracked. Add one with:[/dim] "
            "cointools scout add <address>"
        )
        return

    table = Table(show_header=True, header_style="bold", pad_edge=False, box=None)
    table.add_column("Address", min_width=16)
    table.add_column("Label", min_width=10)
    table.add_column("Added", min_width=12)
    table.add_column("Last Scanned", min_width=12)

    for w in wallets:
        addr = w["address"]
        short = f"{addr[:6]}..{addr[-4:]}"
        label = w.get("label") or "[dim]—[/dim]"
        added = (w.get("added_at") or "")[:10]
        scanned = (
            (w["last_scanned"][:10]) if w.get("last_scanned") else "[dim]never[/dim]"
        )
        table.add_row(short, label, added, scanned)

    console.print(table)
    console.print(f"\n[dim]{len(wallets)} wallet(s) tracked[/dim]")


def render_token_feed(signals: list[TokenSignal], period: str) -> None:
    if not signals:
        console.print("[dim]No token activity found in this period.[/dim]")
        return

    console.print(
        f"\n[bold]Scout Feed[/bold] — [cyan]{period}[/cyan] "
        f"— {len(signals)} tokens\n"
    )

    table = Table(show_header=True, header_style="bold", pad_edge=False, box=None)
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Token", min_width=14)
    table.add_column("Price", justify="right", min_width=10)
    table.add_column("MCap", justify="right", min_width=8)
    table.add_column("Liq", justify="right", min_width=8)
    table.add_column("Buyers", justify="center", min_width=7)
    table.add_column("SOL In", justify="right", min_width=10)
    table.add_column("Net", justify="right", min_width=10)
    table.add_column("Last", justify="right", min_width=8)
    table.add_column("Who", min_width=20)

    for i, s in enumerate(signals, 1):
        net = s.net_flow
        if net > 0:
            net_text = Text(f"+{_fmt_sol(net)}", style="green")
        elif net < 0:
            net_text = Text(f"-{_fmt_sol(abs(net))}", style="red")
        else:
            net_text = Text("0", style="dim")

        if s.unique_buyers >= 3:
            buyers_style = "bold green"
        elif s.unique_buyers >= 2:
            buyers_style = "green"
        else:
            buyers_style = "dim"
        buyers_text = Text(str(s.unique_buyers), style=buyers_style)

        who = ", ".join(s.buyer_labels[:4])
        if len(s.buyer_labels) > 4:
            who += f" +{len(s.buyer_labels) - 4}"

        table.add_row(
            str(i),
            f"[bold]{s.symbol}[/bold] [dim]{s.name[:15]}[/dim]",
            _fmt_usd(s.price_usd),
            _fmt_usd(s.market_cap),
            _fmt_usd(s.liquidity_usd),
            buyers_text,
            _fmt_sol(s.total_sol_in),
            net_text,
            _time_ago(s.last_seen),
            who,
        )

    console.print(table)
    console.print()


def render_scan_summary(
    wallet_count: int,
    trade_count: int,
    new_trades: int,
    token_count: int,
) -> None:
    console.print(
        f"[dim]Scanned {wallet_count} wallets — "
        f"{trade_count} trades ({new_trades} new) — "
        f"{token_count} tokens[/dim]\n"
    )
