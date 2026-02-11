"""Rich terminal display for analysis reports."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from cointools.tracker import AnalysisReport, HolderAnalysis, Sentiment, Signal

console = Console()

_SIGNAL_STYLE = {
    Signal.BUY: ("BUY", "bold green"),
    Signal.SELL: ("SELL", "bold red"),
    Signal.HOLD: ("HOLD", "dim"),
    Signal.NEW: ("NEW", "bold cyan"),
    Signal.UNKNOWN: ("???", "yellow"),
}

_SENTIMENT_STYLE = {
    Sentiment.ACCUMULATION: ("ACCUMULATION", "bold green"),
    Sentiment.DISTRIBUTION: ("DISTRIBUTION", "bold red"),
    Sentiment.NEUTRAL: ("NEUTRAL", "yellow"),
}


def _shorten(addr: str | None, length: int = 4) -> str:
    if not addr:
        return "—"
    if len(addr) <= length * 2 + 2:
        return addr
    return f"{addr[:length]}..{addr[-length:]}"


def _fmt_balance(val: float | None) -> str:
    if val is None:
        return "—"
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:,.2f}B"
    if val >= 1_000_000:
        return f"{val / 1_000_000:,.2f}M"
    if val >= 1_000:
        return f"{val:,.0f}"
    return f"{val:,.2f}"


def _fmt_change(h: HolderAnalysis) -> Text:
    if h.change is None:
        return Text("—", style="dim")
    prefix = "+" if h.change > 0 else ""
    val = _fmt_balance(abs(h.change))
    if h.change > 0:
        text = f"+{val}"
        style = "green"
    elif h.change < 0:
        text = f"-{val}"
        style = "red"
    else:
        text = "0"
        style = "dim"

    if h.change_pct is not None:
        text += f" ({prefix}{h.change_pct:,.1f}%)"

    return Text(text, style=style)


def _signal_text(signal: Signal) -> Text:
    label, style = _SIGNAL_STYLE[signal]
    return Text(label, style=style)


def render_report(report: AnalysisReport) -> None:
    """Print a full analysis report to the terminal."""
    console.print()

    title = f"[bold]{_shorten(report.mint, 6)}[/bold] — Top Holder Analysis ([cyan]{report.period}[/cyan])"
    console.print(title)
    console.print()

    table = Table(show_header=True, header_style="bold", pad_edge=False, box=None)
    table.add_column("Rank", justify="right", style="dim", width=4)
    table.add_column("Owner", min_width=12)
    table.add_column("Balance", justify="right", min_width=12)
    table.add_column("Change", justify="right", min_width=16)
    table.add_column("Signal", justify="center", min_width=6)

    for h in report.holders:
        table.add_row(
            str(h.rank),
            _shorten(h.owner_address or h.holder_address),
            _fmt_balance(h.current_balance),
            _fmt_change(h),
            _signal_text(h.signal),
        )

    console.print(table)
    console.print()

    # Summary line
    parts = []
    if report.buying:
        parts.append(f"[green]{report.buying} buying[/green]")
    if report.selling:
        parts.append(f"[red]{report.selling} selling[/red]")
    if report.holding:
        parts.append(f"[dim]{report.holding} holding[/dim]")
    if report.unknown:
        parts.append(f"[cyan]{report.unknown} new/unknown[/cyan]")

    console.print("  " + " | ".join(parts))

    label, style = _SENTIMENT_STYLE[report.sentiment]
    console.print(f"  Net sentiment: [{style}]{label}[/{style}]")
    console.print()
