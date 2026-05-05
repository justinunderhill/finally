"""SQLite persistence for the single-user FinAlly application."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import DB_PATH

DEFAULT_USER_ID = "default"
DEFAULT_CASH_BALANCE = 10000.0
DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

_write_lock = threading.Lock()


def utc_now() -> str:
    """Return an ISO timestamp in UTC."""
    return datetime.now(UTC).isoformat()


def connect() -> sqlite3.Connection:
    """Open a SQLite connection with dict-like rows."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables and seed the single default user/watchlist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock, connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users_profile (
                id TEXT PRIMARY KEY,
                cash_balance REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                ticker TEXT NOT NULL,
                added_at TEXT NOT NULL,
                UNIQUE(user_id, ticker)
            );

            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                ticker TEXT NOT NULL,
                quantity REAL NOT NULL,
                avg_cost REAL NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, ticker)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                ticker TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                executed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                total_value REAL NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                actions TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at)
            VALUES (?, ?, ?)
            """,
            (DEFAULT_USER_ID, DEFAULT_CASH_BALANCE, utc_now()),
        )
        for ticker in DEFAULT_TICKERS:
            conn.execute(
                """
                INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), DEFAULT_USER_ID, ticker, utc_now()),
            )


def get_watchlist() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at",
            (DEFAULT_USER_ID,),
        ).fetchall()
    return [row["ticker"] for row in rows]


def add_watchlist_ticker(ticker: str) -> None:
    ticker = normalize_ticker(ticker)
    with _write_lock, connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), DEFAULT_USER_ID, ticker, utc_now()),
        )


def remove_watchlist_ticker(ticker: str) -> None:
    ticker = normalize_ticker(ticker)
    with _write_lock, connect() as conn:
        conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (DEFAULT_USER_ID, ticker),
        )


def get_cash_balance() -> float:
    with connect() as conn:
        row = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?",
            (DEFAULT_USER_ID,),
        ).fetchone()
    return float(row["cash_balance"]) if row else DEFAULT_CASH_BALANCE


def get_positions() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT ticker, quantity, avg_cost, updated_at
            FROM positions
            WHERE user_id = ?
            ORDER BY ticker
            """,
            (DEFAULT_USER_ID,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_recent_trades(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT ticker, side, quantity, price, executed_at
            FROM trades
            WHERE user_id = ?
            ORDER BY executed_at DESC
            LIMIT ?
            """,
            (DEFAULT_USER_ID, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_portfolio_history(limit: int = 120) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT total_value, recorded_at
            FROM portfolio_snapshots
            WHERE user_id = ?
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (DEFAULT_USER_ID, limit),
        ).fetchall()
    return list(reversed([dict(row) for row in rows]))


def record_snapshot(total_value: float) -> None:
    with _write_lock, connect() as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), DEFAULT_USER_ID, round(total_value, 2), utc_now()),
        )


def save_chat_message(role: str, content: str, actions: dict[str, Any] | None = None) -> None:
    with _write_lock, connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                DEFAULT_USER_ID,
                role,
                content,
                json.dumps(actions) if actions is not None else None,
                utc_now(),
            ),
        )


def get_recent_chat_messages(limit: int = 8) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT role, content, actions, created_at
            FROM chat_messages
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (DEFAULT_USER_ID, limit),
        ).fetchall()
    messages = list(reversed([dict(row) for row in rows]))
    for message in messages:
        if message.get("actions"):
            message["actions"] = json.loads(message["actions"])
    return messages


def execute_trade(ticker: str, side: str, quantity: float, price: float) -> dict[str, Any]:
    ticker = normalize_ticker(ticker)
    side = side.lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if quantity <= 0:
        raise ValueError("quantity must be greater than 0")
    if price <= 0:
        raise ValueError(f"no current price is available for {ticker}")

    with _write_lock, connect() as conn:
        profile = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?",
            (DEFAULT_USER_ID,),
        ).fetchone()
        cash_balance = float(profile["cash_balance"])
        position = conn.execute(
            """
            SELECT id, quantity, avg_cost
            FROM positions
            WHERE user_id = ? AND ticker = ?
            """,
            (DEFAULT_USER_ID, ticker),
        ).fetchone()

        current_quantity = float(position["quantity"]) if position else 0.0
        avg_cost = float(position["avg_cost"]) if position else 0.0
        notional = round(quantity * price, 2)

        if side == "buy":
            if notional > cash_balance:
                raise ValueError(f"insufficient cash for ${notional:.2f} buy")
            new_quantity = current_quantity + quantity
            new_avg_cost = ((current_quantity * avg_cost) + notional) / new_quantity
            new_cash = cash_balance - notional
            conn.execute(
                """
                INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, ticker) DO UPDATE SET
                    quantity = excluded.quantity,
                    avg_cost = excluded.avg_cost,
                    updated_at = excluded.updated_at
                """,
                (
                    str(uuid.uuid4()),
                    DEFAULT_USER_ID,
                    ticker,
                    round(new_quantity, 6),
                    round(new_avg_cost, 4),
                    utc_now(),
                ),
            )
        else:
            if quantity > current_quantity:
                raise ValueError(f"insufficient shares to sell {quantity:g} {ticker}")
            new_quantity = current_quantity - quantity
            new_cash = cash_balance + notional
            if new_quantity <= 0.000001:
                conn.execute(
                    "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
                    (DEFAULT_USER_ID, ticker),
                )
            else:
                conn.execute(
                    """
                    UPDATE positions
                    SET quantity = ?, updated_at = ?
                    WHERE user_id = ? AND ticker = ?
                    """,
                    (round(new_quantity, 6), utc_now(), DEFAULT_USER_ID, ticker),
                )

        conn.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
            (round(new_cash, 2), DEFAULT_USER_ID),
        )
        trade = {
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
            "notional": notional,
            "executed_at": utc_now(),
        }
        conn.execute(
            """
            INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                DEFAULT_USER_ID,
                ticker,
                side,
                quantity,
                price,
                trade["executed_at"],
            ),
        )
    return trade


def normalize_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 12 or not ticker.replace(".", "").replace("-", "").isalnum():
        raise ValueError("ticker must be a valid symbol")
    return ticker
