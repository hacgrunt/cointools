"""SQLite storage for scout wallet tracking and trade data."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from cointools.config import CACHE_DB, _ensure_config_dir

SCOUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS scout_wallets (
    address      TEXT PRIMARY KEY,
    label        TEXT,
    added_at     TEXT NOT NULL,
    last_scanned TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scout_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT    NOT NULL,
    signature       TEXT    NOT NULL UNIQUE,
    timestamp       INTEGER NOT NULL,
    trade_type      TEXT    NOT NULL,
    token_mint      TEXT    NOT NULL,
    token_amount    REAL    NOT NULL,
    sol_amount      REAL    NOT NULL DEFAULT 0,
    source          TEXT,
    FOREIGN KEY (wallet_address) REFERENCES scout_wallets(address)
);

CREATE INDEX IF NOT EXISTS idx_scout_trades_wallet
    ON scout_trades (wallet_address, timestamp);
CREATE INDEX IF NOT EXISTS idx_scout_trades_token
    ON scout_trades (token_mint, timestamp);
CREATE INDEX IF NOT EXISTS idx_scout_trades_ts
    ON scout_trades (timestamp);
"""


def get_scout_connection(db_path=None) -> sqlite3.Connection:
    _ensure_config_dir()
    path = db_path or CACHE_DB
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCOUT_SCHEMA)
    return conn


def add_wallet(
    conn: sqlite3.Connection, address: str, label: str | None = None
) -> bool:
    """Add a wallet to track. Returns True if newly added."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO scout_wallets (address, label, added_at) VALUES (?, ?, ?)",
            (address, label, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.execute(
            "UPDATE scout_wallets SET is_active = 1, label = COALESCE(?, label) "
            "WHERE address = ?",
            (label, address),
        )
        conn.commit()
        return False


def remove_wallet(conn: sqlite3.Connection, address: str) -> bool:
    """Soft-delete a wallet. Returns True if it was active."""
    cur = conn.execute(
        "UPDATE scout_wallets SET is_active = 0 WHERE address = ? AND is_active = 1",
        (address,),
    )
    conn.commit()
    return cur.rowcount > 0


def list_wallets(
    conn: sqlite3.Connection, active_only: bool = True
) -> list[dict]:
    q = "SELECT * FROM scout_wallets"
    if active_only:
        q += " WHERE is_active = 1"
    q += " ORDER BY added_at"
    return [dict(r) for r in conn.execute(q).fetchall()]


def update_wallet_scan_time(conn: sqlite3.Connection, address: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE scout_wallets SET last_scanned = ? WHERE address = ?",
        (now, address),
    )
    conn.commit()


def upsert_trades(conn: sqlite3.Connection, trades: list[dict]) -> int:
    """Insert trades, skip duplicates on signature. Returns new count."""
    inserted = 0
    for t in trades:
        try:
            conn.execute(
                """INSERT INTO scout_trades
                   (wallet_address, signature, timestamp, trade_type,
                    token_mint, token_amount, sol_amount, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    t["wallet_address"],
                    t["signature"],
                    t["timestamp"],
                    t["trade_type"],
                    t["token_mint"],
                    t["token_amount"],
                    t["sol_amount"],
                    t.get("source"),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted


def get_trades_since(
    conn: sqlite3.Connection,
    since_timestamp: int,
    wallet_address: str | None = None,
    token_mint: str | None = None,
) -> list[dict]:
    q = "SELECT * FROM scout_trades WHERE timestamp >= ?"
    params: list = [since_timestamp]
    if wallet_address:
        q += " AND wallet_address = ?"
        params.append(wallet_address)
    if token_mint:
        q += " AND token_mint = ?"
        params.append(token_mint)
    q += " ORDER BY timestamp DESC"
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def get_token_aggregation(
    conn: sqlite3.Connection, since_timestamp: int
) -> list[dict]:
    """Aggregate trades by token since a timestamp.

    Returns rows with: token_mint, buy_count, sell_count, unique_buyers,
    unique_sellers, total_sol_in, total_sol_out, first_seen, last_seen.
    """
    rows = conn.execute(
        """
        SELECT
            token_mint,
            SUM(CASE WHEN trade_type = 'BUY'  THEN 1 ELSE 0 END) AS buy_count,
            SUM(CASE WHEN trade_type = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
            COUNT(DISTINCT CASE WHEN trade_type = 'BUY'
                  THEN wallet_address END) AS unique_buyers,
            COUNT(DISTINCT CASE WHEN trade_type = 'SELL'
                  THEN wallet_address END) AS unique_sellers,
            SUM(CASE WHEN trade_type = 'BUY'
                 THEN sol_amount ELSE 0 END) AS total_sol_in,
            SUM(CASE WHEN trade_type = 'SELL'
                 THEN sol_amount ELSE 0 END) AS total_sol_out,
            MIN(timestamp) AS first_seen,
            MAX(timestamp) AS last_seen
        FROM scout_trades
        WHERE timestamp >= ?
        GROUP BY token_mint
        ORDER BY unique_buyers DESC, total_sol_in DESC
        """,
        (since_timestamp,),
    ).fetchall()
    return [dict(r) for r in rows]
