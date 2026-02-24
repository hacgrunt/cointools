"""HTTP + WebSocket server for the Miners tracker dashboard."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from pathlib import Path

from aiohttp import web

from cointools.miners.scraper import scrape_miners

logger = logging.getLogger(__name__)

POLL_INTERVAL = 900  # 15 minutes
CSV_PATH = Path.home() / ".cointools" / "miners.csv"
DASHBOARD_PATH = Path(__file__).resolve().parent.parent.parent.parent / "web" / "miners.html"
CSV_FIELDS = ["timestamp", "active_miners", "epoch", "epoch_rewards", "total_mined"]


def _ensure_csv() -> None:
    """Create CSV with header if it doesn't exist."""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_FIELDS)


def _append_csv(row: dict) -> None:
    """Append a single data point to the CSV."""
    _ensure_csv()
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([row.get(k, "") for k in CSV_FIELDS])


def _load_csv() -> list[dict]:
    """Load all historical data from CSV."""
    _ensure_csv()
    rows = []
    with open(CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                entry = {
                    "timestamp": int(r["timestamp"]),
                    "active_miners": int(r["active_miners"]) if r.get("active_miners") else None,
                    "epoch": int(r["epoch"]) if r.get("epoch") else None,
                    "epoch_rewards": r.get("epoch_rewards") or None,
                    "total_mined": r.get("total_mined") or None,
                }
                if entry["active_miners"] is not None:
                    rows.append(entry)
            except (ValueError, KeyError):
                continue
    return rows


class MinersServer:
    """Tracks active miner count from agentmoney.net over time."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8421) -> None:
        self.host = host
        self.port = port
        self.clients: set[web.WebSocketResponse] = set()
        self.history: list[dict] = []
        self.latest: dict | None = None
        self._poll_task: asyncio.Task | None = None

    # ── HTTP handlers ────────────────────────────────────────────

    async def _index(self, request: web.Request) -> web.Response:
        if DASHBOARD_PATH.exists():
            return web.FileResponse(DASHBOARD_PATH)
        return web.Response(text="miners.html not found", status=404)

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "clients": len(self.clients),
            "data_points": len(self.history),
        })

    async def _csv_download(self, request: web.Request) -> web.Response:
        """Serve the raw CSV file for download."""
        if CSV_PATH.exists():
            return web.FileResponse(
                CSV_PATH,
                headers={"Content-Disposition": "attachment; filename=miners.csv"},
            )
        return web.Response(text="No data yet", status=404)

    # ── WebSocket handler ────────────────────────────────────────

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self.clients.add(ws)
        logger.info("Client connected (%d total)", len(self.clients))

        # Send full history immediately
        try:
            payload = json.dumps({
                "type": "init",
                "history": self.history,
                "latest": self.latest,
            })
            await ws.send_str(payload)
        except Exception:
            pass

        try:
            async for msg in ws:
                pass
        finally:
            self.clients.discard(ws)
            logger.info("Client disconnected (%d remaining)", len(self.clients))

        return ws

    # ── Broadcasting ─────────────────────────────────────────────

    async def _broadcast(self, payload: str) -> None:
        if not self.clients:
            return
        dead: list[web.WebSocketResponse] = []
        for ws in self.clients:
            try:
                await ws.send_str(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    # ── Poll loop ────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        logger.info("Poll loop started (interval=%ds / %d min)", POLL_INTERVAL, POLL_INTERVAL // 60)

        # Do an immediate first scrape
        await self._poll_once()

        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Poll error")

    async def _poll_once(self) -> None:
        logger.info("Scraping agentmoney.net ...")
        try:
            data = await scrape_miners()
        except Exception as e:
            logger.error("Scrape failed: %s", e)
            return

        if data.get("active_miners") is None:
            logger.warning("No miner count found — skipping this data point")
            return

        self.latest = data
        self.history.append(data)
        _append_csv(data)

        logger.info(
            "Recorded: %d miners (epoch %s) — %d total data points",
            data["active_miners"],
            data.get("epoch", "?"),
            len(self.history),
        )

        payload = json.dumps({
            "type": "update",
            "point": data,
            "history": self.history,
        })
        await self._broadcast(payload)

    # ── App lifecycle ────────────────────────────────────────────

    async def _on_startup(self, app: web.Application) -> None:
        # Load existing CSV data
        self.history = _load_csv()
        if self.history:
            self.latest = self.history[-1]
            logger.info("Loaded %d historical data points from CSV", len(self.history))

        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _on_cleanup(self, app: web.Application) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/health", self._health)
        app.router.add_get("/ws", self._ws_handler)
        app.router.add_get("/csv", self._csv_download)
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        return app

    def run(self) -> None:
        app = self.build_app()
        web.run_app(app, host=self.host, port=self.port, print=None)
