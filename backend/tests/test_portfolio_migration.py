import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd

from main import app
from scheduler import _snapshot_job, start_scheduler
from services.portfolio.db import get_connection, init_db
from services.portfolio.holdings_service import record_trade
from services.portfolio.repository import AccountRepository
from services.db_schema import run_merge_strategies_migration


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
    frames = {
        "v_a_daily": pd.DataFrame([{"_symbol": "600519.SH", "date": "2026-08-19", "close": 1500.0}]),
        "v_hk_daily": pd.DataFrame([{"_symbol": "00005.HK", "date": "2026-08-19", "close": 300.0}]),
        "v_us_daily": pd.DataFrame([{"_symbol": "AAPL.US", "date": "2026-08-18", "close": 200.0}]),
    }
    store = type(
        "Store",
        (),
        {"query": lambda self, sql: next(frame for view, frame in frames.items() if view in sql)},
    )()
    connection = MagicMock()

    with patch("services.market_data.duckdb_store.get_store", return_value=store), patch(
        "services.portfolio.db.get_connection", return_value=connection
    ), patch("services.portfolio.db.init_db"), patch(
        "services.portfolio.holdings_service.take_all_snapshots"
    ) as take_snapshots:
        _snapshot_job()

    take_snapshots.assert_called_once_with(
        {
            "A": ("2026-08-19", {"600519.SH": 1500.0}),
            "HK": ("2026-08-19", {"00005.HK": 300.0}),
            "US": ("2026-08-18", {"AAPL.US": 200.0}),
        },
        connection=connection,
    )


def test_v1_snapshot_service_persists_account_valuation():
    from services.portfolio.holdings_service import take_all_snapshots

    conn = get_connection(":memory:")
    try:
        init_db(conn)
        repo = AccountRepository(conn)
        accounts = [
            repo.create_account("A账户", "A", "CNY"),
            repo.create_account("港股账户", "HK", "HKD"),
            repo.create_account("美股账户", "US", "USD"),
        ]
        record_trade(accounts[0].id, "600519", "buy", 2, 100.0, "2026-08-19", connection=conn)
        record_trade(accounts[1].id, "00005", "buy", 2, 100.0, "2026-08-19", connection=conn)
        record_trade(accounts[2].id, "AAPL", "buy", 2, 100.0, "2026-08-19", connection=conn)

        take_all_snapshots(
            {
                "A": ("2026-08-19", {"600519.SH": 120.0}),
                "HK": ("2026-08-19", {"00005.HK": 120.0}),
                "US": ("2026-08-19", {}),
            },
            connection=conn,
        )

        row = conn.execute(
            "SELECT account_id, total_value, market_value FROM portfolio_account_snapshots ORDER BY account_id"
        ).fetchall()
        assert [tuple(item) for item in row] == [(1, 240.0, 240.0), (2, 240.0, 240.0), (3, 0.0, 0.0)]
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


def test_populated_duplicate_active_execution_is_archived_deterministically():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE backtest_tasks (task_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, pipeline_info TEXT, execution_account_id INTEGER, execution_status TEXT NOT NULL DEFAULT 'inactive')")
    conn.executemany(
        "INSERT INTO backtest_tasks(task_id, status, created_at, execution_account_id, execution_status) VALUES (?, 'success', ?, 7, 'active')",
        [("task-b", "2026-08-20T00:00:00"), ("task-a", "2026-08-19T00:00:00")],
    )
    conn.commit()

    run_merge_strategies_migration(conn)

    rows = conn.execute("SELECT task_id, execution_status, execution_account_id FROM backtest_tasks ORDER BY task_id").fetchall()
    assert [tuple(row) for row in rows] == [
        ("task-a", "active", 7),
        ("task-b", "inactive", None),
    ]
    run_merge_strategies_migration(conn)
    assert [tuple(row) for row in conn.execute("SELECT task_id, execution_status, execution_account_id FROM backtest_tasks ORDER BY task_id")] == [
        ("task-a", "active", 7),
        ("task-b", "inactive", None),
    ]
    conn.close()
