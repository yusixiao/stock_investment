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

    # 这是共享 SQLite 的启动 bootstrap；回测和问股表不能随旧 Portfolio
    # 接口删除而丢失，Portfolio v1 schema 也在此统一幂等初始化。
    from services.db_schema import (
        init_backtest_tables,
        init_chat_tables,
        init_portfolio_v1_tables,
    )

    init_backtest_tables(conn)
    init_chat_tables(conn)
    init_portfolio_v1_tables(conn)

    if close_after:
        conn.close()
