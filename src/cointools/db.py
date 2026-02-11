"""SQLite cache for analysis results."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cointools.config import CACHE_DB, _ensure_config_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mint_address    TEXT    NOT NULL,
    holder_address  TEXT    NOT NULL,
    owner_address   TEXT,
    current_balance REAL    NOT NULL,
    historical_balance REAL,
    period          TEXT    NOT NULL,
    analyzed_at     TEXT    NOT NULL,
    rank            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_mint_period
    ON analysis_cache (mint_address, period, analyzed_at);
"""


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    _ensure_config_dir()
    path = db_path or CACHE_DB
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_analysis(
    conn: sqlite3.Connection,
    mint_address: str,
    period: str,
    holders: list[dict],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            mint_address,
            h["holder_address"],
            h.get("owner_address"),
            h["current_balance"],
            h.get("historical_balance"),
            period,
            now,
            h["rank"],
        )
        for h in holders
    ]
    conn.executemany(
        """INSERT INTO analysis_cache
           (mint_address, holder_address, owner_address, current_balance,
            historical_balance, period, analyzed_at, rank)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def get_latest_analysis(
    conn: sqlite3.Connection, mint_address: str, period: str
) -> list[dict] | None:
    rows = conn.execute(
        """SELECT * FROM analysis_cache
           WHERE mint_address = ? AND period = ?
           ORDER BY analyzed_at DESC, rank ASC
           LIMIT 20""",
        (mint_address, period),
    ).fetchall()
    if not rows:
        return None
    # All rows should share the same analyzed_at timestamp
    target_time = rows[0]["analyzed_at"]
    return [dict(r) for r in rows if r["analyzed_at"] == target_time]
