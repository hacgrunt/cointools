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
    SUPPORTED_CHAINS,
    detect_chain,
    get_rpc_url,
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
@click.argument("key", type=click.Choice(["rpc_url"]))
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


@config.command("get")
@click.argument("key", type=click.Choice(["rpc_url"]))
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
