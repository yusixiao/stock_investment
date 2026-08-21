import sqlite3

import pytest

from services.db_schema import init_portfolio_v1_tables
from services.monitoring.repository import MonitoringRepository
from services.monitoring.strategy_monitor import (
    is_due,
    next_run_date,
    run_due_strategy_monitors,
)


class TradingDateStore:
    def __init__(self, dates):
        self.dates = dates

    def get_trading_dates(self, market, start_date=None, end_date=None):
        dates = self.dates[market]
        return [
            date for date in dates
            if (start_date is None or date >= start_date)
            and (end_date is None or date <= end_date)
        ]


def make_connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_portfolio_v1_tables(conn)
    return conn


@pytest.fixture
def store():
    return TradingDateStore({
        "A": [
            "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-30",
            "2026-02-02", "2026-03-31", "2026-04-01", "2026-04-02",
            "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-31",
            "2026-09-01", "2026-10-01", "2026-10-02",
        ]
    })


def test_schedule_due_dates_for_all_supported_frequencies(store):
    assert is_due("daily", "A", "2026-08-21", store)
    assert is_due("weekly", "A", "2026-08-24", store)
    assert not is_due("weekly", "A", "2026-08-25", store)
    assert is_due("monthly", "A", "2026-08-03", TradingDateStore({"A": ["2026-08-03"]}))
    assert is_due("quarterly", "A", "2026-10-01", store)
    assert not is_due("quarterly", "A", "2026-09-01", store)
    assert next_run_date("weekly", "A", "2026-08-21", store) == "2026-08-24"
    assert next_run_date("monthly", "A", "2026-08-21", store) == "2026-09-01"
    assert next_run_date("quarterly", "A", "2026-08-21", store) == "2026-10-01"


def test_due_monitor_with_running_run_cannot_be_claimed_twice(store):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-21"
    )
    repo.create_strategy_run(monitor.id, "2026-08-21")

    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 0
    assert len(repo.list_strategy_runs(monitor.id)) == 1


def test_successful_run_persists_result_task_and_advances_schedule(store, monkeypatch):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-21"
    )
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.execute_strategy_current_date",
        lambda monitor, as_of_date, store: {"task_id": "task-1", "hits": ["600000"]},
    )

    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 1
    run = repo.list_strategy_runs(monitor.id)[0]
    assert run.status == "success"
    assert run.task_id == "task-1"
    assert run.result == {"task_id": "task-1", "hits": ["600000"]}
    assert repo.get_strategy_monitor(monitor.id).next_run_date == "2026-08-24"


def test_failed_run_keeps_previous_success_result(store, monkeypatch):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-21"
    )
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.execute_strategy_current_date",
        lambda monitor, as_of_date, store: {"task_id": "task-1", "value": 3},
    )
    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 1
    assert repo.get_strategy_monitor(monitor.id).next_run_date == "2026-08-24"

    def fail(monitor, as_of_date, store):
        raise RuntimeError("current-date data unavailable")

    monkeypatch.setattr("services.monitoring.strategy_monitor.execute_strategy_current_date", fail)
    assert run_due_strategy_monitors("2026-08-24", connection=conn, store=store) == 1
    runs = repo.list_strategy_runs(monitor.id)
    assert runs[0].status == "failed"
    assert "current-date data unavailable" in runs[0].error
    assert runs[1].result == {"task_id": "task-1", "value": 3}
    assert repo.get_strategy_monitor(monitor.id).next_run_date == "2026-08-24"


def test_default_execution_seam_records_unexecuted_instead_of_fake_success(store):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "MissingStrategy", "missing.py", {}, "A", "daily", next_run_date="2026-08-21"
    )

    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 1
    run = repo.list_strategy_runs(monitor.id)[0]
    assert run.status == "failed"
    assert run.result["status"] == "unexecuted"
    assert run.error
