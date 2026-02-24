"""Scrape active miner count from agentmoney.net."""

from __future__ import annotations

import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

URL = "https://agentmoney.net"
TIMEOUT = 20

# Multiple regex strategies — we don't know the exact HTML structure,
# so we try several patterns from strict to loose.

# Strategy 1: label in one tag, value in the next tag
_RE_MINERS_STRICT = re.compile(
    r"ACTIVE\s+MINERS\s*</[^>]+>\s*<[^>]+>\s*([\d,]+)", re.IGNORECASE
)
# Strategy 2: label and value separated by any tags/whitespace
_RE_MINERS_MED = re.compile(
    r"ACTIVE\s+MINERS.*?>([\d,]{1,10})<", re.IGNORECASE | re.DOTALL
)
# Strategy 3: just find digits near the phrase
_RE_MINERS_LOOSE = re.compile(
    r"active.{0,5}miners.{0,80}?(\d[\d,]{0,8})", re.IGNORECASE | re.DOTALL
)

_RE_EPOCH = re.compile(r"CURRENT\s+EPOCH.*?>([\d,]+)<", re.IGNORECASE | re.DOTALL)
_RE_REWARDS = re.compile(
    r"EPOCH\s+REWARDS.*?>([\d,.]+\s*[MBK]?\s*BOTCOIN)", re.IGNORECASE | re.DOTALL
)
_RE_TOTAL = re.compile(
    r"TOTAL\s+BOTCOIN\s+MINED.*?>([\d,.]+\s*[MBK]?\s*BOTCOIN)", re.IGNORECASE | re.DOTALL
)


def _parse_num(s: str) -> float:
    return float(s.replace(",", ""))


def _extract_miners(html: str) -> int | None:
    for pat in (_RE_MINERS_STRICT, _RE_MINERS_MED, _RE_MINERS_LOOSE):
        m = pat.search(html)
        if m:
            try:
                return int(_parse_num(m.group(1)))
            except ValueError:
                continue
    return None


async def scrape_miners(client: httpx.AsyncClient | None = None) -> dict:
    """Fetch agentmoney.net and return parsed stats.

    Returns dict with keys:
        timestamp: int (unix epoch)
        active_miners: int | None
        epoch: int | None
        epoch_rewards: str | None
        total_mined: str | None
        raw_html_len: int  (for debugging — size of fetched HTML)
    """
    close_client = False
    if client is None:
        client = httpx.AsyncClient(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            follow_redirects=True,
            timeout=TIMEOUT,
        )
        close_client = True

    try:
        resp = await client.get(URL)
        resp.raise_for_status()
        html = resp.text
    finally:
        if close_client:
            await client.aclose()

    miners = _extract_miners(html)

    epoch = None
    m = _RE_EPOCH.search(html)
    if m:
        try:
            epoch = int(_parse_num(m.group(1)))
        except ValueError:
            pass

    rewards_raw = None
    m = _RE_REWARDS.search(html)
    if m:
        rewards_raw = m.group(1).strip()

    total_raw = None
    m = _RE_TOTAL.search(html)
    if m:
        total_raw = m.group(1).strip()

    result = {
        "timestamp": int(time.time()),
        "active_miners": miners,
        "epoch": epoch,
        "epoch_rewards": rewards_raw,
        "total_mined": total_raw,
        "raw_html_len": len(html),
    }

    if miners is None:
        logger.warning(
            "Could not parse active miners from HTML (%d bytes). "
            "The page may use JavaScript rendering. "
            "First 500 chars: %s",
            len(html),
            html[:500],
        )
    else:
        logger.info("Scraped: active_miners=%d epoch=%s", miners, epoch)

    return result
