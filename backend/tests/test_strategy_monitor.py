import sqlite3
from types import SimpleNamespace

import pytest

from services.db_schema import init_portfolio_v1_tables
from services.monitoring.repository import MonitoringRepository
from services.monitoring import strategy_monitor
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


@pytest.fixture(autouse=True)
def inline_strategy_dispatch(monkeypatch):
    def submit(monitor, run, as_of_date, **kwargs):
        strategy_monitor._execute_claimed_strategy_run(
            monitor,
            run.id,
            as_of_date,
            connection=kwargs["connection"],
            store=kwargs["store"],
        )

    monkeypatch.setattr(strategy_monitor, "_submit_strategy_run", submit)


def test_schedule_due_dates_for_all_supported_frequencies(store):
    assert is_due("daily", "A", "2026-08-21", store)
    assert is_due("weekly", "A", "2026-08-24", store)
    assert not is_due("weekly", "A", "2026-08-25", store)
    assert is_due("monthly", "A", "2026-08-03", TradingDateStore({"A": ["2026-08-03"]}))
    assert is_due("quarterly", "A", "2026-10-01", store)
    assert not is_due("quarterly", "A", "2026-09-01", store)
    assert not is_due("quarterly", "A", "2026-02-02", TradingDateStore({"A": ["2026-02-02"]}))
    assert next_run_date("weekly", "A", "2026-08-21", store) == "2026-08-24"
    assert next_run_date("weekly", "A", "2026-08-24", store) == "2026-08-31"
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
    assert repo.get_strategy_monitor(monitor.id).next_run_date == "2026-08-25"


def test_failed_run_is_processed_only_once(store, monkeypatch):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-21"
    )
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.execute_strategy_current_date",
        lambda monitor, as_of_date, store: (_ for _ in ()).throw(RuntimeError("down")),
    )

    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 1
    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 0
    assert len(repo.list_strategy_runs(monitor.id)) == 1


@pytest.mark.parametrize(
    ("frequency", "latest_date", "next_date"),
    [
        ("daily", "2026-08-21", "2026-08-24"),
        ("weekly", "2026-08-24", "2026-08-31"),
        ("monthly", "2026-08-03", "2026-09-01"),
        ("quarterly", "2026-10-01", "2027-01-04"),
    ],
)
def test_latest_data_date_without_next_run_is_retried_once_then_waits_for_new_data(
    frequency, latest_date, next_date, monkeypatch
):
    dates = [latest_date]
    calendar = TradingDateStore({"A": dates})
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", frequency, next_run_date=None
    )
    calls = []
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.execute_strategy_current_date",
        lambda monitor, as_of_date, store: calls.append(as_of_date) or {"status": "success"},
    )

    assert run_due_strategy_monitors(latest_date, connection=conn, store=calendar) == 1
    assert run_due_strategy_monitors(latest_date, connection=conn, store=calendar) == 0
    assert calls == [latest_date]
    assert repo.get_strategy_monitor(monitor.id).next_run_date is None

    dates.append(next_date)
    assert run_due_strategy_monitors(next_date, connection=conn, store=calendar) == 1
    assert calls == [latest_date, next_date]


def test_current_date_execution_uses_loaded_snapshot(monkeypatch):
    class FakeStrategy:
        def __init__(self, param_overrides=None):
            self.frequency = "daily"

    engine = SimpleNamespace(run_scan=lambda: {"events": {"600000": [("2026-08-21", {})]}, "all_symbols_count": 1})
    monkeypatch.setattr(strategy_monitor, "load_strategy_from_file", lambda path: [FakeStrategy])
    monkeypatch.setattr(strategy_monitor, "create_snapshot", lambda *args, **kwargs: "snapshot")
    monkeypatch.setattr(strategy_monitor, "BacktestEngine", lambda **kwargs: engine)
    monkeypatch.setattr(
        strategy_monitor.data_cache,
        "get_market",
        lambda market: SimpleNamespace(stock_data={"600000": object()}),
    )
    monitor = SimpleNamespace(
        filepath="/trusted/deployed.py",
        strategy_class="FakeStrategy",
        params={},
        market="A",
        symbols=["600000"],
    )

    outcome = strategy_monitor.execute_strategy_current_date(monitor, "2026-08-21", object())

    assert outcome["status"] == "success"
    assert outcome["as_of_date"] == "2026-08-21"
    assert outcome["hits"] == ["600000"]


def test_initial_run_date_is_next_available_frequency_date(store):
    assert strategy_monitor.initial_run_date("weekly", "A", store, today="2026-08-21") == "2026-08-24"


@pytest.mark.parametrize("frequency", ["weekly", "monthly", "quarterly"])
def test_initial_run_date_does_not_fall_back_to_historical_due_date(frequency):
    calendar = TradingDateStore({"A": ["2026-01-02", "2026-01-05"]})

    assert strategy_monitor.initial_run_date(frequency, "A", calendar, today="2026-01-06") is None


def test_running_run_for_previous_date_does_not_block_current_date(store, monkeypatch):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-24"
    )
    previous = repo.create_strategy_run(monitor.id, "2026-08-21")
    submitted = []
    monkeypatch.setattr(
        strategy_monitor,
        "_submit_strategy_run",
        lambda monitor, run, as_of_date, **kwargs: submitted.append((monitor.id, run.id, as_of_date)),
    )

    assert run_due_strategy_monitors("2026-08-24", connection=conn, store=store) == 1
    assert submitted == [(monitor.id, previous.id + 1, "2026-08-24")]
    assert repo.list_strategy_runs(monitor.id)[0].status == "running"


def test_stale_run_is_reclaimed_for_same_date_without_creating_duplicate(store, monkeypatch):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-21"
    )
    stale = repo.create_strategy_run(monitor.id, "2026-08-21")
    conn.execute(
        "UPDATE monitoring_strategy_runs SET started_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00", stale.id),
    )
    conn.commit()
    submitted = []
    monkeypatch.setattr(
        strategy_monitor,
        "_submit_strategy_run",
        lambda monitor, run, as_of_date, **kwargs: submitted.append((run.id, as_of_date)),
    )

    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 1
    assert submitted == [(stale.id, "2026-08-21")]
    assert len(repo.list_strategy_runs(monitor.id)) == 1


def test_dispatch_failure_finishes_run_and_advances_schedule(store, monkeypatch):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-21"
    )
    monkeypatch.setattr(
        strategy_monitor,
        "_submit_strategy_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("executor unavailable")),
    )

    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 1
    run = repo.list_strategy_runs(monitor.id)[0]
    assert run.status == "failed"
    assert run.error == "executor unavailable"
    assert repo.get_strategy_monitor(monitor.id).next_run_date == "2026-08-24"


def test_older_date_completion_does_not_overwrite_newer_schedule(store):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-25"
    )
    older = repo.create_strategy_run(monitor.id, "2026-08-21")

    strategy_monitor._finish_claimed_run(
        conn, repo, monitor, older.id, "2026-08-21", outcome={"status": "success"}, store=store
    )

    assert repo.get_strategy_monitor(monitor.id).next_run_date == "2026-08-25"


def test_default_execution_failure_is_recorded_as_failed(store):
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


def test_existing_caller_transaction_is_not_committed(store, monkeypatch):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    monitor = repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-21"
    )
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.execute_strategy_current_date",
        lambda monitor, as_of_date, store: {"task_id": "task-1"},
    )

    assert conn.in_transaction
    assert run_due_strategy_monitors("2026-08-21", connection=conn, store=store) == 1
    assert conn.in_transaction
    assert repo.get_strategy_monitor(monitor.id).last_run_status == "success"
    conn.rollback()


def test_owned_connection_comes_from_monitoring_service_factory(store, monkeypatch):
    conn = make_connection()
    repo = MonitoringRepository(conn)
    repo.create_strategy_monitor(
        "strategy", "Strategy", "strategy.py", {}, "A", "daily", next_run_date="2026-08-21"
    )
    factory_calls = []

    def factory():
        factory_calls.append(True)
        return conn

    monkeypatch.setattr(strategy_monitor, "get_monitoring_connection", factory)
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.execute_strategy_current_date",
        lambda monitor, as_of_date, store: {"task_id": "task-1"},
    )

    assert run_due_strategy_monitors("2026-08-21", store=store) == 1
    assert factory_calls == [True]
