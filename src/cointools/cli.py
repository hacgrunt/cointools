"""CLI entry point for cointools."""

from __future__ import annotations

import asyncio
import sys
import time

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from cointools.config import (
    PERIOD_SECONDS,
    SCOUT_PERIOD_SECONDS,
    SUPPORTED_CHAINS,
    detect_chain,
    get_helius_api_key,
    get_rpc_url,
    set_helius_api_key,
    set_rpc_url,
)
from cointools.db import get_connection, save_analysis
from cointools.display import render_report
from cointools.tracker import build_report

console = Console()


def _resolve_chain(address: str, chain: str | None) -> str:
    if chain:
        return chain
    detected = detect_chain(address)
    console.print(f"[dim]Auto-detected chain: {detected}[/dim]")
    return detected


def _is_evm_chain(chain: str) -> bool:
    return chain != "solana"


def _run_analysis(chain: str, address: str, period_secs: int, rpc_url: str | None, on_progress):
    """Run the appropriate chain analysis."""
    if _is_evm_chain(chain):
        from cointools.chains.evm import analyze_holders as evm_analyze
        return asyncio.run(
            evm_analyze(chain, address, period_secs, rpc_url, on_progress)
        )
    else:
        from cointools.chains.solana import analyze_holders as sol_analyze
        url = rpc_url or get_rpc_url("solana")
        return asyncio.run(
            sol_analyze(url, address, period_secs, on_progress)
        )


@click.group()
def cli() -> None:
    """Cointools: on-demand top holder behavior analysis for on-chain tokens."""


@cli.command()
@click.argument("address")
@click.option(
    "--chain",
    "-c",
    type=click.Choice(SUPPORTED_CHAINS),
    default=None,
    help="Blockchain to query (auto-detected from address if omitted).",
)
@click.option(
    "--period",
    "-p",
    type=click.Choice(list(PERIOD_SECONDS.keys())),
    default="24h",
    help="How far back to look (default: 24h).",
)
@click.option(
    "--rpc",
    type=str,
    default=None,
    help="Override the RPC endpoint for this run.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Skip writing results to local cache.",
)
@click.option(
    "--html",
    type=click.Path(),
    default=None,
    help="Export an HTML report to this path.",
)
def analyze(
    address: str,
    chain: str | None,
    period: str,
    rpc: str | None,
    no_cache: bool,
    html: str | None,
) -> None:
    """Analyze top holder behavior for a token.

    ADDRESS is the token mint (Solana) or contract address (EVM).
    Chain is auto-detected from the address format, or specify with --chain.
    """
    chain = _resolve_chain(address, chain)
    period_secs = PERIOD_SECONDS[period]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Analyzing top holders on {chain} ({period})...", total=None
        )

        def on_progress(msg: str) -> None:
            progress.update(task, description=msg)

        try:
            holders_data = _run_analysis(chain, address, period_secs, rpc, on_progress)
        except RuntimeError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Unexpected error:[/red] {e}")
            sys.exit(1)

    if not holders_data:
        console.print("[yellow]No holders found for this address.[/yellow]")
        sys.exit(1)

    report = build_report(address, period, holders_data)
    render_report(report)

    if html:
        from cointools.export import generate_html_report
        generate_html_report(report, html)
        console.print(f"[green]HTML report saved to:[/green] {html}")

    if not no_cache:
        try:
            conn = get_connection()
            save_analysis(conn, address, period, holders_data)
            conn.close()
        except Exception:
            pass


@cli.command()
@click.argument("address")
@click.option(
    "--chain",
    "-c",
    type=click.Choice(SUPPORTED_CHAINS),
    default=None,
    help="Blockchain to query (auto-detected if omitted).",
)
@click.option(
    "--period",
    "-p",
    type=click.Choice(list(PERIOD_SECONDS.keys())),
    default="24h",
    help="How far back to look (default: 24h).",
)
@click.option(
    "--interval",
    "-i",
    type=int,
    default=300,
    help="Seconds between each analysis cycle (default: 300).",
)
@click.option(
    "--rpc",
    type=str,
    default=None,
    help="Override the RPC endpoint for this run.",
)
def watch(
    address: str,
    chain: str | None,
    period: str,
    interval: int,
    rpc: str | None,
) -> None:
    """Continuously analyze top holder behavior at a set interval.

    ADDRESS is the token mint (Solana) or contract address (EVM).
    """
    chain = _resolve_chain(address, chain)
    period_secs = PERIOD_SECONDS[period]

    console.print(
        f"[bold]Watching[/bold] {address[:8]}.. on {chain} every {interval}s "
        f"(period: {period}). Press Ctrl+C to stop.\n"
    )

    try:
        while True:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("Fetching...", total=None)

                def on_progress(msg: str) -> None:
                    progress.update(task, description=msg)

                try:
                    holders_data = _run_analysis(chain, address, period_secs, rpc, on_progress)
                except Exception as e:
                    console.print(f"[red]Error:[/red] {e}")
                    console.print(f"Retrying in {interval}s...\n")
                    time.sleep(interval)
                    continue

            if holders_data:
                report = build_report(address, period, holders_data)
                render_report(report)
                try:
                    conn = get_connection()
                    save_analysis(conn, address, period, holders_data)
                    conn.close()
                except Exception:
                    pass

            console.print(f"[dim]Next update in {interval}s...[/dim]\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[bold]Stopped.[/bold]")


@cli.group()
def config() -> None:
    """Manage cointools configuration."""


@config.command("set")
@click.argument("key", type=click.Choice(["rpc_url", "helius_api_key"]))
@click.argument("value")
@click.option(
    "--chain",
    "-c",
    type=click.Choice(SUPPORTED_CHAINS),
    default="solana",
    help="Chain this RPC applies to (default: solana).",
)
def config_set(key: str, value: str, chain: str) -> None:
    """Set a configuration value."""
    if key == "rpc_url":
        set_rpc_url(value, chain)
        console.print(f"[green]RPC URL for {chain} set to:[/green] {value}")
    elif key == "helius_api_key":
        set_helius_api_key(value)
        console.print("[green]Helius API key saved.[/green]")


@config.command("get")
@click.argument("key", type=click.Choice(["rpc_url", "helius_api_key"]))
@click.option(
    "--chain",
    "-c",
    type=click.Choice(SUPPORTED_CHAINS),
    default="solana",
    help="Chain to query (default: solana).",
)
def config_get(key: str, chain: str) -> None:
    """Show a configuration value."""
    if key == "rpc_url":
        console.print(get_rpc_url(chain))
    elif key == "helius_api_key":
        k = get_helius_api_key()
        if k:
            console.print(f"{k[:8]}...{k[-4:]}")
        else:
            console.print("[dim]Not set. Use: cointools config set helius_api_key <key>[/dim]")


# ── Scout: smart money token discovery ────────────────────────────────


@cli.group()
def scout() -> None:
    """Smart money token discovery — track what good wallets are buying."""


@scout.command("add")
@click.argument("address")
@click.option("--label", "-l", default=None, help="Human-readable label for this wallet.")
def scout_add(address: str, label: str | None) -> None:
    """Add a wallet to the scout watchlist."""
    from cointools.scout.db import add_wallet, get_scout_connection

    conn = get_scout_connection()
    is_new = add_wallet(conn, address, label)
    conn.close()
    if is_new:
        tag = f" ({label})" if label else ""
        console.print(f"[green]Added[/green] {address[:8]}..{address[-4:]}{tag}")
    else:
        console.print(f"[yellow]Already tracked[/yellow] — reactivated {address[:8]}..{address[-4:]}")


@scout.command("remove")
@click.argument("address")
def scout_remove(address: str) -> None:
    """Remove a wallet from the scout watchlist."""
    from cointools.scout.db import get_scout_connection, remove_wallet

    conn = get_scout_connection()
    removed = remove_wallet(conn, address)
    conn.close()
    if removed:
        console.print(f"[green]Removed[/green] {address[:8]}..{address[-4:]}")
    else:
        console.print(f"[yellow]Wallet not found in active watchlist.[/yellow]")


@scout.command("list")
def scout_list() -> None:
    """Show all tracked wallets."""
    from cointools.scout.db import get_scout_connection, list_wallets
    from cointools.scout.display import render_wallet_list

    conn = get_scout_connection()
    wallets = list_wallets(conn)
    conn.close()
    render_wallet_list(wallets)


@scout.command("scan")
@click.option(
    "--period",
    "-p",
    type=click.Choice(list(SCOUT_PERIOD_SECONDS.keys())),
    default="24h",
    help="How far back to scan (default: 24h).",
)
def scout_scan(period: str) -> None:
    """Scan tracked wallets and display the token feed.

    Fetches recent swap transactions from all tracked wallets via the
    Helius Enhanced Transactions API, aggregates by token, fetches
    metadata from DexScreener, and ranks by smart-wallet conviction.
    """
    import httpx

    from cointools.scout.aggregator import build_token_feed
    from cointools.scout.db import (
        get_scout_connection,
        get_token_aggregation,
        get_trades_since,
        list_wallets,
        update_wallet_scan_time,
        upsert_trades,
    )
    from cointools.scout.display import render_scan_summary, render_token_feed
    from cointools.scout.scanner import scan_all_wallets
    from cointools.scout.tokens import fetch_token_metadata

    api_key = get_helius_api_key()
    if not api_key:
        console.print(
            "[red]Helius API key required.[/red]\n"
            "Set it with: cointools config set helius_api_key <key>\n"
            "Get a free key at https://dev.helius.xyz"
        )
        sys.exit(1)

    conn = get_scout_connection()
    wallets = list_wallets(conn)
    if not wallets:
        console.print(
            "[yellow]No wallets tracked.[/yellow]\n"
            "Add wallets first: cointools scout add <address> --label name"
        )
        conn.close()
        sys.exit(1)

    period_secs = SCOUT_PERIOD_SECONDS[period]
    since = int(time.time()) - period_secs
    addresses = [w["address"] for w in wallets]
    wallet_labels = {w["address"]: w.get("label") or w["address"][:8] + ".." for w in wallets}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting scan...", total=None)

        def on_progress(msg: str) -> None:
            progress.update(task, description=msg)

        try:
            trades = asyncio.run(
                scan_all_wallets(api_key, addresses, since, on_progress)
            )
        except Exception as e:
            console.print(f"[red]Scan failed:[/red] {e}")
            conn.close()
            sys.exit(1)

        # Persist trades
        trade_dicts = [
            {
                "wallet_address": t["wallet_address"],
                "signature": t["signature"],
                "timestamp": t["timestamp"],
                "trade_type": t["trade_type"],
                "token_mint": t["token_mint"],
                "token_amount": t["token_amount"],
                "sol_amount": t["sol_amount"],
                "source": t.get("source"),
            }
            for t in trades
        ]
        new_count = upsert_trades(conn, trade_dicts)
        for addr in addresses:
            update_wallet_scan_time(conn, addr)

        # Aggregate
        progress.update(task, description="Aggregating signals...")
        agg = get_token_aggregation(conn, since)
        all_trades = get_trades_since(conn, since)
        token_mints = [a["token_mint"] for a in agg]

        # Fetch metadata
        if token_mints:
            progress.update(task, description=f"Fetching metadata for {len(token_mints)} tokens...")
            metadata = asyncio.run(
                _fetch_metadata_wrapper(token_mints)
            )
        else:
            metadata = {}

    feed = build_token_feed(agg, metadata, wallet_labels, all_trades)
    render_scan_summary(len(addresses), len(trades), new_count, len(feed))
    render_token_feed(feed, period)
    conn.close()


async def _fetch_metadata_wrapper(mints: list[str]) -> dict:
    """Wrapper to run DexScreener fetch in an async context."""
    import httpx

    from cointools.scout.tokens import fetch_token_metadata

    async with httpx.AsyncClient() as client:
        return await fetch_token_metadata(client, mints)
