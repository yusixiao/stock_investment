"""Strategy monitor scheduling and the deliberately small execution seam."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from services.backtest.strategy_loader import load_strategy_from_file
from services.monitoring.models import StrategyMonitor
from services.monitoring.repository import FREQUENCIES, MonitoringRepository


def _period_key(frequency: str, value: date) -> tuple[int, ...]:
    if frequency == "daily":
        return (value.toordinal(),)
    if frequency == "weekly":
        return (value.isocalendar().year, value.isocalendar().week)
    if frequency == "monthly":
        return (value.year, value.month)
    if frequency == "quarterly":
        return (value.year, (value.month - 1) // 3)
    raise ValueError(f"invalid frequency: {frequency}")


def _dates(store: Any, market: str, start: str | None = None, end: str | None = None) -> list[str]:
    if hasattr(store, "get_trading_dates"):
        values = store.get_trading_dates(market, start, end)
        return sorted(str(value)[:10] for value in values)
    # DuckDBStore is intentionally queried through its public query seam; no
    # monitor code reads parquet or invents a calendar.
    frame = store.query(
        f"SELECT DISTINCT CAST(date AS DATE) AS trading_date "
        f"FROM v_{market.lower()}_daily ORDER BY trading_date"
    )
    values = [str(value)[:10] for value in frame["trading_date"].tolist()]
    return [value for value in values if (start is None or value >= start) and (end is None or value <= end)]


def is_due(frequency: str, market: str, as_of_date: str, store: Any) -> bool:
    if frequency not in FREQUENCIES:
        raise ValueError(f"invalid frequency: {frequency}")
    current = date.fromisoformat(as_of_date)
    available = _dates(store, market, as_of_date, as_of_date)
    if as_of_date not in available:
        return False
    period = _period_key(frequency, current)
    period_dates = [
        value for value in _dates(store, market)
        if _period_key(frequency, date.fromisoformat(value)) == period
    ]
    return bool(period_dates) and as_of_date == period_dates[0]


def next_run_date(frequency: str, market: str, after_date: str, store: Any) -> str | None:
    if frequency not in FREQUENCIES:
        raise ValueError(f"invalid frequency: {frequency}")
    for value in _dates(store, market, after_date):
        if value > after_date and is_due(frequency, market, value, store):
            return value
    return None


def execute_strategy_current_date(monitor: StrategyMonitor, as_of_date: str, store: Any) -> dict[str, Any]:
    """Validate/load a strategy, but never pretend the historical engine is current-date safe.

    A future live execution implementation can replace this service seam. Until
    it can establish a real current-date data snapshot, returning ``unexecuted``
    is safer than feeding a fabricated historical window to BacktestEngine.
    """
    try:
        classes = load_strategy_from_file(Path(monitor.filepath))
    except Exception as exc:
        return {"status": "unexecuted", "reason": f"strategy unavailable: {exc}", "as_of_date": as_of_date}
    strategy_cls = next((cls for cls in classes if cls.__name__ == monitor.strategy_class), None)
    if strategy_cls is None:
        return {
            "status": "unexecuted",
            "reason": f"strategy class not found: {monitor.strategy_class}",
            "as_of_date": as_of_date,
        }
    try:
        strategy_cls(param_overrides=monitor.params)
    except Exception as exc:
        return {"status": "unexecuted", "reason": f"strategy config invalid: {exc}", "as_of_date": as_of_date}
    return {
        "status": "unexecuted",
        "reason": "current-date strategy execution is not safely available",
        "as_of_date": as_of_date,
    }


def _claim(repo: MonitoringRepository, monitor: StrategyMonitor, scheduled_date: str):
    conn = repo.conn
    # Callers may have just created a monitor on a default sqlite connection;
    # finish that unit of work before acquiring the cross-process write lock.
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute(
            "SELECT * FROM monitoring_strategy_monitors WHERE id = ? AND is_active = 1 AND next_run_date = ?",
            (monitor.id, scheduled_date),
        ).fetchone()
        running = conn.execute(
            "SELECT 1 FROM monitoring_strategy_runs WHERE monitor_id = ? AND status = 'running' LIMIT 1",
            (monitor.id,),
        ).fetchone()
        if current is None or running is not None:
            conn.rollback()
            return None
        run = repo.create_strategy_run(monitor.id, scheduled_date)
        conn.commit()
        return run
    except Exception:
        conn.rollback()
        raise


def run_due_strategy_monitors(
    as_of_date: str,
    markets: set[str] | None = None,
    connection: sqlite3.Connection | None = None,
    store: Any = None,
) -> int:
    owned_connection = connection is None
    if connection is None:
        from services.portfolio.db import get_connection, init_db

        connection = get_connection()
        init_db(connection)
    if store is None:
        from services.market_data.duckdb_store import DuckDBStore

        store = DuckDBStore()

    repo = MonitoringRepository(connection)
    claimed = 0
    try:
        for monitor in repo.list_strategy_monitors():
            if markets is not None and monitor.market not in markets:
                continue
            if monitor.next_run_date != as_of_date:
                continue
            if not is_due(monitor.frequency, monitor.market, as_of_date, store):
                continue
            run = _claim(repo, monitor, as_of_date)
            if run is None:
                continue
            claimed += 1
            try:
                outcome = execute_strategy_current_date(monitor, as_of_date, store)
                if outcome.get("status") == "unexecuted":
                    repo.finish_strategy_run(run.id, "failed", result=outcome, error=outcome["reason"])
                    continue
                task_id = outcome.get("task_id")
                connection.execute("BEGIN IMMEDIATE")
                if task_id is not None:
                    connection.execute(
                        "UPDATE monitoring_strategy_runs SET task_id = ? WHERE id = ? AND status = 'running'",
                        (str(task_id), run.id),
                    )
                repo.finish_strategy_run(run.id, "success", result=outcome)
                following = next_run_date(monitor.frequency, monitor.market, as_of_date, store)
                repo.update_strategy_monitor(monitor.id, next_run_date=following)
                connection.commit()
            except Exception as exc:
                if connection.in_transaction:
                    connection.rollback()
                repo.finish_strategy_run(run.id, "failed", error=str(exc))
    finally:
        if owned_connection:
            connection.close()
    return claimed
