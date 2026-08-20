import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd

from main import app
from scheduler import _snapshot_job, start_scheduler
from services.portfolio.db import get_connection, init_db
from services.portfolio.holdings_service import record_trade
from services.portfolio.repository import AccountRepository


def test_production_app_only_exposes_portfolio_v1():
    paths = {route.path for route in app.routes}

    assert "/api/v1/portfolio/accounts" in paths
    assert not any(path == "/api/portfolio/" or path.startswith("/api/portfolio/") for path in paths)


def test_portfolio_bootstrap_preserves_shared_backtest_and_chat_tables():
    conn = sqlite3.connect(":memory:")
    try:
        init_db(conn)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"backtest_tasks", "chat_sessions", "chat_messages", "portfolio_accounts"} <= tables
    finally:
        conn.close()


def test_snapshot_job_uses_duckdb_and_v1_holdings_service():
    frame = pd.DataFrame(
        [
            {"_symbol": "600519.SH", "date": "2026-08-19", "close": 1500.0},
            {"_symbol": "000001.SZ", "date": "2026-08-18", "close": 10.0},
        ]
    )
    store = type("Store", (), {"query": lambda self, sql: frame})()
    connection = MagicMock()

    with patch("services.market_data.duckdb_store.get_store", return_value=store), patch(
        "services.portfolio.db.get_connection", return_value=connection
    ), patch("services.portfolio.db.init_db"), patch(
        "services.portfolio.holdings_service.take_all_snapshots"
    ) as take_snapshots:
        _snapshot_job()

    take_snapshots.assert_called_once_with(
        "2026-08-19",
        {"600519.SH": 1500.0, "000001.SZ": 10.0},
        connection=connection,
    )


def test_v1_snapshot_service_persists_account_valuation():
    from services.portfolio.holdings_service import take_all_snapshots

    conn = get_connection(":memory:")
    try:
        init_db(conn)
        account = AccountRepository(conn).create_account("账户", "A", "CNY")
        record_trade(account.id, "600519.SH", "buy", 2, 100.0, "2026-08-19", connection=conn)

        take_all_snapshots(
            "2026-08-19", {"600519.SH": 120.0}, connection=conn
        )

        row = conn.execute(
            "SELECT account_id, date, total_value, market_value, cash "
            "FROM portfolio_account_snapshots"
        ).fetchone()
        assert tuple(row) == (account.id, "2026-08-19", 240.0, 240.0, 0.0)
    finally:
        conn.close()


def test_snapshot_schedule_remains_at_1530():
    with patch.object(start_scheduler.__globals__["scheduler"], "add_job") as add_job, patch.object(
        start_scheduler.__globals__["scheduler"], "start"
    ):
        start_scheduler()

    snapshot_call = next(call for call in add_job.call_args_list if call.kwargs.get("id") == "daily_snapshot")
    assert snapshot_call.kwargs["hour"] == 15
    assert snapshot_call.kwargs["minute"] == 30
