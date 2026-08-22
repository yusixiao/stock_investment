import sqlite3

from services.db_schema import (
    init_backtest_tables,
    init_market_refresh_tables,
    init_monitoring_tables,
)


def test_runtime_schema_creates_backtest_refresh_and_monitoring_tables_without_product_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "runtime.db")
    init_backtest_tables(conn)
    init_market_refresh_tables(conn)
    init_monitoring_tables(conn)

    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"backtest_tasks", "stock_exclusions", "market_refreshes", "market_refresh_versions"} <= tables
    assert {
        "monitoring_strategy_monitors",
        "monitoring_strategy_runs",
        "monitoring_stock_monitors",
        "monitoring_stock_events",
    } <= tables
    assert "portfolio_accounts" not in tables
    assert "chat_sessions" not in tables
    conn.close()


def test_runtime_schema_preserves_old_product_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.execute("CREATE TABLE portfolio_accounts (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY)")
    conn.commit()

    init_backtest_tables(conn)
    init_market_refresh_tables(conn)
    init_monitoring_tables(conn)

    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"portfolio_accounts", "chat_sessions"} <= tables
    conn.close()
