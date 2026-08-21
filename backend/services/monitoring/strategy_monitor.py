"""Strategy monitor scheduling and the deliberately small execution seam."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
from typing import Any

from services.backtest.strategy_loader import load_strategy_from_file
from services.backtest import data_cache
from services.backtest.data_snapshot import create_snapshot
from services.backtest.engine import BacktestEngine
from services.monitoring.models import StrategyMonitor
from services.monitoring.repository import FREQUENCIES, MonitoringRepository


logger = logging.getLogger(__name__)
STRATEGY_RUN_STALE_AFTER = timedelta(hours=1)
_STRATEGY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="strategy-monitor")


def get_monitoring_connection() -> sqlite3.Connection:
    """Open the shared SQLite file without depending on the Portfolio domain."""
    from config import PORTFOLIO_DB
    from services.db_schema import init_portfolio_v1_tables

    connection = sqlite3.connect(str(PORTFOLIO_DB))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    init_portfolio_v1_tables(connection)
    return connection


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


def _is_due_from_dates(frequency: str, as_of_date: str, dates: list[str]) -> bool:
    current = date.fromisoformat(as_of_date)
    if as_of_date not in dates:
        return False
    if frequency == "quarterly" and current.month not in {1, 4, 7, 10}:
        return False
    period = _period_key(frequency, current)
    period_dates = [
        value for value in dates
        if _period_key(frequency, date.fromisoformat(value)) == period
    ]
    return bool(period_dates) and as_of_date == period_dates[0]


def is_due(frequency: str, market: str, as_of_date: str, store: Any) -> bool:
    if frequency not in FREQUENCIES:
        raise ValueError(f"invalid frequency: {frequency}")
    return _is_due_from_dates(frequency, as_of_date, _dates(store, market))


def next_run_date(frequency: str, market: str, after_date: str, store: Any) -> str | None:
    if frequency not in FREQUENCIES:
        raise ValueError(f"invalid frequency: {frequency}")
    dates = _dates(store, market)
    for value in dates:
        if value > after_date and _is_due_from_dates(frequency, value, dates):
            return value
    return None


def initial_run_date(
    frequency: str, market: str, store: Any, today: str | None = None
) -> str | None:
    """Choose the first calendar date on which a new monitor can run."""
    if frequency not in FREQUENCIES:
        raise ValueError(f"invalid frequency: {frequency}")
    anchor = today or date.today().isoformat()
    dates = _dates(store, market)
    comparison = (lambda value: value >= anchor) if frequency == "daily" else (lambda value: value > anchor)
    candidates = [value for value in dates if comparison(value) and _is_due_from_dates(frequency, value, dates)]
    if candidates:
        return candidates[0]
    return None


def execute_strategy_current_date(monitor: StrategyMonitor, as_of_date: str, store: Any) -> dict[str, Any]:
    """Run only the latest loaded bar, never a fabricated historical window."""
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
        strategy = strategy_cls(param_overrides=monitor.params)
    except Exception as exc:
        return {"status": "unexecuted", "reason": f"strategy config invalid: {exc}", "as_of_date": as_of_date}
    if store is None:
        from services.market_data.duckdb_store import get_store

        store = get_store()
    from services.backtest import data_cache

    bundle = data_cache.get_market(monitor.market)
    if bundle is None:
        return {"status": "unexecuted", "reason": "market data is not loaded", "as_of_date": as_of_date}
    try:
        snapshot = create_snapshot(bundle, monitor.market, monitor.symbols, as_of_date, as_of_date)
        result = BacktestEngine(
            strategy=strategy, snapshot=snapshot, enable_decision_log=False
        ).run_scan()
    except Exception as exc:
        return {"status": "unexecuted", "reason": f"current-date execution unavailable: {exc}", "as_of_date": as_of_date}
    return {
        "status": "success",
        "as_of_date": as_of_date,
        "hits": sorted(result["events"]),
        "total_scanned": result["all_symbols_count"],
    }


def _is_stale_run(started_at: str) -> bool:
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return True
    if started.tzinfo is not None:
        started = started.replace(tzinfo=None)
    return datetime.now() - started > STRATEGY_RUN_STALE_AFTER


def _finish_claimed_run(
    connection: sqlite3.Connection,
    repo: MonitoringRepository,
    monitor: StrategyMonitor,
    run_id: int,
    as_of_date: str,
    outcome: dict[str, Any] | None = None,
    error: str | None = None,
    store: Any = None,
    commit: bool = True,
) -> None:
    if error is not None:
        repo.finish_strategy_run(run_id, "failed", error=error)
    elif outcome is not None and outcome.get("status") == "unexecuted":
        repo.finish_strategy_run(run_id, "failed", result=outcome, error=outcome["reason"])
    else:
        task_id = outcome.get("task_id") if outcome else None
        if task_id is not None:
            connection.execute(
                "UPDATE monitoring_strategy_runs SET task_id = ? WHERE id = ? AND status = 'running'",
                (str(task_id), run_id),
            )
        repo.finish_strategy_run(run_id, "success", result=outcome or {})
    following = next_run_date(monitor.frequency, monitor.market, as_of_date, store)
    current = repo.get_strategy_monitor(monitor.id)
    if current is not None and current.next_run_date in {None, as_of_date}:
        repo.update_strategy_monitor(monitor.id, next_run_date=following)
    if commit:
        connection.commit()


def _execute_claimed_strategy_run(
    monitor: StrategyMonitor,
    run_id: int,
    as_of_date: str,
    connection: sqlite3.Connection | None = None,
    store: Any = None,
) -> None:
    owned_connection = connection is None
    if connection is None:
        connection = get_monitoring_connection()
    if store is None:
        from services.market_data.duckdb_store import DuckDBStore

        store = DuckDBStore()
    repo = MonitoringRepository(connection)
    try:
        try:
            outcome = execute_strategy_current_date(monitor, as_of_date, store)
            _finish_claimed_run(
                connection, repo, monitor, run_id, as_of_date,
                outcome=outcome, store=store, commit=owned_connection,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("strategy monitor run failed: monitor=%s date=%s", monitor.id, as_of_date)
            _finish_claimed_run(
                connection, repo, monitor, run_id, as_of_date,
                error=str(exc), store=store, commit=owned_connection,
            )
    finally:
        if owned_connection:
            connection.close()


def _submit_strategy_run(
    monitor: StrategyMonitor,
    run: Any,
    as_of_date: str,
    *,
    connection: sqlite3.Connection | None = None,
    store: Any = None,
) -> None:
    """Dispatch work to a bounded executor; scheduler/API only claim and return."""
    _STRATEGY_EXECUTOR.submit(_execute_claimed_strategy_run, monitor, run.id, as_of_date)


def submit_strategy_run(monitor: StrategyMonitor, run: Any, as_of_date: str) -> None:
    _submit_strategy_run(monitor, run, as_of_date)


def _claim(repo: MonitoringRepository, monitor: StrategyMonitor, scheduled_date: str):
    conn = repo.conn
    owns_transaction = not conn.in_transaction
    savepoint = f"strategy_monitor_claim_{monitor.id}"
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    else:
        conn.execute(f"SAVEPOINT {savepoint}")
    try:
        current = conn.execute(
            "SELECT * FROM monitoring_strategy_monitors "
            "WHERE id = ? AND is_active = 1 AND (next_run_date = ? OR next_run_date IS NULL)",
            (monitor.id, scheduled_date),
        ).fetchone()
        existing = conn.execute(
            "SELECT * FROM monitoring_strategy_runs WHERE monitor_id = ? AND scheduled_date = ?",
            (monitor.id, scheduled_date),
        ).fetchone()
        if current is None:
            if owns_transaction:
                conn.rollback()
            else:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            return None
        if existing is not None:
            if existing["status"] == "running" and _is_stale_run(existing["started_at"]):
                run = repo.reclaim_strategy_run(existing["id"])
            else:
                if owns_transaction:
                    conn.rollback()
                else:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                return None
        else:
            run = repo.create_strategy_run(monitor.id, scheduled_date)
        if owns_transaction:
            conn.commit()
        else:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return run, owns_transaction
    except Exception:
        if owns_transaction:
            conn.rollback()
        else:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def run_due_strategy_monitors(
    as_of_date: str,
    markets: set[str] | None = None,
    connection: sqlite3.Connection | None = None,
    store: Any = None,
) -> int:
    owned_connection = connection is None
    if connection is None:
        connection = get_monitoring_connection()
    if store is None:
        from services.market_data.duckdb_store import DuckDBStore

        store = DuckDBStore()

    repo = MonitoringRepository(connection)
    claimed = 0
    try:
        for monitor in repo.list_strategy_monitors():
            if markets is not None and monitor.market not in markets:
                continue
            # None means the loaded calendar has no future date yet. Evaluate
            # today's due rule and let _claim deduplicate repeated scheduler calls.
            if monitor.next_run_date is not None and monitor.next_run_date != as_of_date:
                continue
            if not is_due(monitor.frequency, monitor.market, as_of_date, store):
                continue
            claimed_run = _claim(repo, monitor, as_of_date)
            if claimed_run is None:
                continue
            run, owns_claim_transaction = claimed_run
            claimed += 1
            try:
                _submit_strategy_run(monitor, run, as_of_date, connection=connection, store=store)
            except Exception as exc:  # noqa: BLE001
                logger.exception("strategy monitor dispatch failed: monitor=%s date=%s", monitor.id, as_of_date)
                _finish_claimed_run(
                    connection, repo, monitor, run.id, as_of_date,
                    error=str(exc), store=store, commit=owns_claim_transaction,
                )
    finally:
        if owned_connection:
            connection.close()
    return claimed
