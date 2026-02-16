"""HTTP + WebSocket server for the Pulse dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import web

from cointools.pulse.scanner import PulseScanner
from cointools.pulse.scorer import score_and_rank

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
        self.token_history: dict[str, list[list]] = {}  # addr → [[ts, score], ...]
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

    async def _poll_once(self) -> None:
        t0 = time.time()
        raw_tokens = await self.scanner.poll()
        scored = score_and_rank(raw_tokens)

        # Update history
        now = time.time()
        for token in scored:
            addr = token["address"]
            if addr not in self.token_history:
                self.token_history[addr] = []
            self.token_history[addr].append([round(now), token["score"]])
            # Trim to max history
            if len(self.token_history[addr]) > MAX_HISTORY:
                self.token_history[addr] = self.token_history[addr][-MAX_HISTORY:]

        # Prune history for tokens no longer in results
        active_addrs = {t["address"] for t in scored}
        stale = [a for a in self.token_history if a not in active_addrs]
        for a in stale:
            # Keep stale entries for a while in case they come back
            if len(self.token_history[a]) > 0:
                age = now - self.token_history[a][-1][0]
                if age > 600:  # 10 minutes stale → remove
                    del self.token_history[a]

        # Attach history and trim to max tokens
        top = scored[:MAX_TOKENS]
        for token in top:
            token["history"] = self.token_history.get(token["address"], [])

        elapsed = round(time.time() - t0, 2)
        payload = json.dumps({
            "type": "update",
            "timestamp": round(now),
            "poll_ms": round(elapsed * 1000),
            "total_discovered": len(raw_tokens),
            "total_scored": len(scored),
            "tokens": top,
        })
        self.latest_payload = payload

        logger.info(
            "Poll complete: %d discovered, %d scored, %d clients, %.1fs",
            len(raw_tokens),
            len(scored),
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
