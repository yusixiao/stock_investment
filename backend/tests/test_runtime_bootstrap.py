import asyncio
import sqlite3
from types import SimpleNamespace

import main


def test_lifespan_bootstraps_runtime_tables_without_importing_portfolio_db(monkeypatch):
    events = []
    connection = sqlite3.connect(":memory:")

    monkeypatch.setattr(
        main,
        "sqlite3",
        SimpleNamespace(connect=lambda *_args, **_kwargs: connection),
        raising=False,
    )
    monkeypatch.setattr(
        "services.db_schema.init_runtime_tables",
        lambda conn: events.append(("runtime_tables", conn)),
    )
    monkeypatch.setattr("services.market_data.duckdb_store.init_duckdb_with_health_check", lambda: events.append("duckdb"))
    monkeypatch.setattr("services.market_data.duckdb_store.shutdown_duckdb", lambda: events.append("duckdb_shutdown"))
    monkeypatch.setattr("services.market_data.stock_index.init_stock_index", lambda: events.append("stock_index"))
    monkeypatch.setattr("services.market_data.refresh_state.RefreshStateStore", lambda: SimpleNamespace(recover_interrupted=lambda: events.append("recover")))
    monkeypatch.setattr("services.backtest.data_cache.load_market_async", lambda market: events.append(("cache", market)))
    monkeypatch.setattr(main, "start_scheduler", lambda: events.append("scheduler"))
    monkeypatch.setattr(main, "shutdown_scheduler", lambda: events.append("scheduler_shutdown"))

    async def exercise_lifespan():
        async with main.lifespan(main.app):
            pass

    asyncio.run(exercise_lifespan())

    assert events == [
        ("runtime_tables", connection),
        "recover",
        "duckdb",
        "stock_index",
        ("cache", "A"),
        "scheduler",
        "scheduler_shutdown",
        "duckdb_shutdown",
    ]
    connection.close()
