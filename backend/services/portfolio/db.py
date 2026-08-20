import sqlite3
from pathlib import Path
from config import PORTFOLIO_DB


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = str(PORTFOLIO_DB)
    conn = sqlite3.Connection(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection | None = None):
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            initial_capital REAL NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            price REAL NOT NULL,
            shares INTEGER NOT NULL,
            commission REAL NOT NULL,
            tax REAL NOT NULL,
            trade_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            cash REAL NOT NULL,
            market_value REAL NOT NULL,
            UNIQUE(portfolio_id, date)
        );
    """)
    conn.commit()
    from services.db_schema import init_portfolio_v1_tables

    init_portfolio_v1_tables(conn)

    if close_after:
        conn.close()
