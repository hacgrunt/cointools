"""HTTP + WebSocket server for the Pulse dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import web

from cointools.pulse.scanner import PulseScanner
from cointools.pulse.scorer import score_and_rank, score_and_rank_momentum

logger = logging.getLogger(__name__)

POLL_INTERVAL = 15  # seconds between API polls
MAX_HISTORY = 60  # score history entries per token (~15 min at 15s)
MAX_TOKENS = 100  # max tokens to send to clients
DASHBOARD_PATH = Path(__file__).resolve().parent.parent.parent.parent / "web" / "pulse.html"


class PulseServer:
    """Real-time Solana attention scanner server."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8420) -> None:
        self.host = host
        self.port = port
        self.scanner = PulseScanner()
        self.clients: set[web.WebSocketResponse] = set()
        # Per-mode score history: mode → addr → [[ts, score], ...]
        self.token_history: dict[str, dict[str, list[list]]] = {
            "accumulation": {},
            "momentum": {},
        }
        self.latest_payload: str = ""
        self._poll_task: asyncio.Task | None = None

    # ── HTTP handlers ────────────────────────────────────────────

    async def _index(self, request: web.Request) -> web.Response:
        if DASHBOARD_PATH.exists():
            return web.FileResponse(DASHBOARD_PATH)
        return web.Response(text="pulse.html not found", status=404)

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "clients": len(self.clients)})

    # ── WebSocket handler ────────────────────────────────────────

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self.clients.add(ws)
        logger.info("Client connected (%d total)", len(self.clients))

        # Send current state immediately
        if self.latest_payload:
            try:
                await ws.send_str(self.latest_payload)
            except Exception:
                pass

        try:
            async for msg in ws:
                pass  # Clients don't send meaningful messages
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
        """Continuously poll DexScreener and push updates."""
        logger.info("Poll loop started (interval=%ds)", POLL_INTERVAL)
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Poll error")
            await asyncio.sleep(POLL_INTERVAL)

    def _update_history(self, mode: str, scored: list[dict], now: float) -> None:
        """Update score history for a given mode."""
        hist = self.token_history[mode]
        for token in scored:
            addr = token["address"]
            if addr not in hist:
                hist[addr] = []
            hist[addr].append([round(now), token["score"]])
            if len(hist[addr]) > MAX_HISTORY:
                hist[addr] = hist[addr][-MAX_HISTORY:]

        active_addrs = {t["address"] for t in scored}
        stale = [a for a in hist if a not in active_addrs]
        for a in stale:
            if hist[a]:
                age = now - hist[a][-1][0]
                if age > 600:
                    del hist[a]

    async def _poll_once(self) -> None:
        t0 = time.time()
        raw_tokens = await self.scanner.poll()

        # Score in both modes
        accum_scored = score_and_rank(raw_tokens)
        momentum_scored = score_and_rank_momentum(raw_tokens)

        now = time.time()
        self._update_history("accumulation", accum_scored, now)
        self._update_history("momentum", momentum_scored, now)

        # Attach history and trim
        accum_top = accum_scored[:MAX_TOKENS]
        for token in accum_top:
            token["history"] = self.token_history["accumulation"].get(token["address"], [])

        momentum_top = momentum_scored[:MAX_TOKENS]
        for token in momentum_top:
            token["history"] = self.token_history["momentum"].get(token["address"], [])

        elapsed = round(time.time() - t0, 2)
        payload = json.dumps({
            "type": "update",
            "timestamp": round(now),
            "poll_ms": round(elapsed * 1000),
            "total_discovered": len(raw_tokens),
            "accumulation": {
                "total_scored": len(accum_scored),
                "tokens": accum_top,
            },
            "momentum": {
                "total_scored": len(momentum_scored),
                "tokens": momentum_top,
            },
        })
        self.latest_payload = payload

        logger.info(
            "Poll complete: %d discovered, %d accum / %d momentum, %d clients, %.1fs",
            len(raw_tokens),
            len(accum_scored),
            len(momentum_scored),
            len(self.clients),
            elapsed,
        )

        await self._broadcast(payload)

    # ── App lifecycle ────────────────────────────────────────────

    async def _on_startup(self, app: web.Application) -> None:
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _on_cleanup(self, app: web.Application) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        await self.scanner.close()

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/health", self._health)
        app.router.add_get("/ws", self._ws_handler)
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        return app

    def run(self) -> None:
        app = self.build_app()
        web.run_app(app, host=self.host, port=self.port, print=None)
