import sqlite3

from services.db_schema import init_portfolio_v1_tables
from services.monitoring import stock_price_monitor
from services.monitoring.repository import MonitoringRepository
from services.monitoring.stock_price_monitor import evaluate_stock_price_monitors


class FakeStore:
    def __init__(self, dates=None, closes=None, failures=None):
        self.dates = dates or {}
        self.closes = closes or {}
        self.failures = failures or set()

    def previous_trading_date(self, market, before_date):
        if (market, "date") in self.failures:
            raise RuntimeError(f"date query failed for {market}")
        return self.dates.get(market)

    def query_previous_close(self, market, symbols, valuation_date):
        if (market, "close") in self.failures:
            raise RuntimeError(f"close query failed for {market}")
        return self.closes.get(market, {})


def make_connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_portfolio_v1_tables(connection)
    return connection


def test_low_close_records_one_event_and_triggers_monitor():
    connection = make_connection()
    repo = MonitoringRepository(connection)
    monitor = repo.create_stock_monitor("A", "600000", 10.0)
    store = FakeStore(dates={"A": "2026-08-20"}, closes={"A": {"600000.SH": 9.5}})

    assert evaluate_stock_price_monitors("2026-08-21", connection=connection, store=store) == 1
    assert repo.get_stock_monitor(monitor.id).state == "triggered"
    assert len(repo.list_stock_events(monitor.id)) == 1


def test_low_close_does_not_duplicate_a_triggered_monitor():
    connection = make_connection()
    repo = MonitoringRepository(connection)
    monitor = repo.create_stock_monitor("HK", "00005", 100.0)
    store = FakeStore(dates={"HK": "2026-08-20"}, closes={"HK": {"00005.HK": 99.0}})

    assert evaluate_stock_price_monitors("2026-08-21", connection=connection, store=store) == 1
    assert evaluate_stock_price_monitors("2026-08-22", connection=connection, store=store) == 0
    assert len(repo.list_stock_events(monitor.id)) == 1


def test_close_at_threshold_rearms_triggered_monitor_without_event():
    connection = make_connection()
    repo = MonitoringRepository(connection)
    monitor = repo.create_stock_monitor("US", "AAPL", 100.0)
    repo.claim_price_trigger(monitor.id, 99.0, "2026-08-20", "2026-08-20T16:00:00")
    store = FakeStore(dates={"US": "2026-08-21"}, closes={"US": {"AAPL.US": 100.0}})

    assert evaluate_stock_price_monitors("2026-08-22", connection=connection, store=store) == 0
    assert repo.get_stock_monitor(monitor.id).state == "armed"
    assert len(repo.list_stock_events(monitor.id)) == 1


def test_initial_armed_monitor_at_threshold_does_not_trigger():
    connection = make_connection()
    repo = MonitoringRepository(connection)
    monitor = repo.create_stock_monitor("A", "600004", 10.0)
    store = FakeStore(dates={"A": "2026-08-20"}, closes={"A": {"600004.SH": 10.0}})

    assert evaluate_stock_price_monitors("2026-08-21", connection=connection, store=store) == 0
    assert repo.get_stock_monitor(monitor.id).state == "armed"
    assert repo.list_stock_events(monitor.id) == []


def test_successful_close_always_refreshes_last_price():
    connection = make_connection()
    repo = MonitoringRepository(connection)
    monitor = repo.create_stock_monitor("A", "600004", 10.0)
    store = FakeStore(dates={"A": "2026-08-20"}, closes={"A": {"600004.SH": 12.0}})

    assert evaluate_stock_price_monitors("2026-08-21", connection=connection, store=store) == 0
    refreshed = repo.get_stock_monitor(monitor.id)
    assert refreshed.last_price == 12.0
    assert refreshed.last_price_date == "2026-08-20"


def test_rearm_persists_with_passed_connection(tmp_path):
    db_path = tmp_path / "monitoring.db"
    seed = sqlite3.connect(db_path)
    seed.row_factory = sqlite3.Row
    init_portfolio_v1_tables(seed)
    monitor = MonitoringRepository(seed).create_stock_monitor("US", "MSFT", 100.0)
    seed.commit()
    seed.close()

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    repo = MonitoringRepository(connection)
    repo.claim_price_trigger(monitor.id, 99.0, "2026-08-20", "2026-08-20T16:00:00")
    store = FakeStore(dates={"US": "2026-08-21"}, closes={"US": {"MSFT.US": 100.0}})

    assert evaluate_stock_price_monitors("2026-08-22", connection=connection, store=store) == 0

    check = sqlite3.connect(db_path)
    assert check.execute("SELECT state FROM monitoring_stock_monitors WHERE id = ?", (monitor.id,)).fetchone()[0] == "armed"


def test_default_connection_rearms_and_allows_a_second_event(tmp_path, monkeypatch):
    db_path = tmp_path / "monitoring.db"
    seed = sqlite3.connect(db_path)
    seed.row_factory = sqlite3.Row
    init_portfolio_v1_tables(seed)
    monitor = MonitoringRepository(seed).create_stock_monitor("A", "600000", 10.0)
    seed.commit()
    seed.close()

    def get_connection():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(stock_price_monitor, "_get_connection", get_connection)
    low_store = FakeStore(dates={"A": "2026-08-20"}, closes={"A": {"600000.SH": 9.0}})
    high_store = FakeStore(dates={"A": "2026-08-21"}, closes={"A": {"600000.SH": 10.0}})

    assert evaluate_stock_price_monitors("2026-08-21", store=low_store) == 1
    assert evaluate_stock_price_monitors("2026-08-22", store=high_store) == 0
    assert evaluate_stock_price_monitors("2026-08-23", store=low_store) == 1

    check = sqlite3.connect(db_path)
    assert check.execute("SELECT state FROM monitoring_stock_monitors WHERE id = ?", (monitor.id,)).fetchone()[0] == "triggered"
    assert check.execute("SELECT COUNT(*) FROM monitoring_stock_events WHERE monitor_id = ?", (monitor.id,)).fetchone()[0] == 2


def test_paused_and_inactive_monitors_are_ignored():
    connection = make_connection()
    repo = MonitoringRepository(connection)
    paused = repo.create_stock_monitor("A", "600001", 10.0)
    inactive = repo.create_stock_monitor("A", "600002", 10.0)
    repo.pause_stock_monitor(paused.id)
    repo.soft_delete_stock_monitor(inactive.id)
    store = FakeStore(dates={"A": "2026-08-20"}, closes={"A": {"600001.SH": 9.0, "600002.SH": 9.0}})

    assert evaluate_stock_price_monitors("2026-08-21", connection=connection, store=store) == 0
    assert repo.get_stock_monitor(paused.id).state == "paused"
    assert repo.get_stock_monitor(inactive.id).state == "armed"


def test_missing_price_does_not_change_state():
    connection = make_connection()
    repo = MonitoringRepository(connection)
    monitor = repo.create_stock_monitor("A", "600003", 10.0)
    store = FakeStore(dates={"A": "2026-08-20"}, closes={"A": {}})

    assert evaluate_stock_price_monitors("2026-08-21", connection=connection, store=store) == 0
    assert repo.get_stock_monitor(monitor.id).state == "armed"
    assert repo.list_stock_events(monitor.id) == []


def test_failed_market_query_does_not_block_another_market():
    connection = make_connection()
    repo = MonitoringRepository(connection)
    failed = repo.create_stock_monitor("HK", "00005", 100.0)
    healthy = repo.create_stock_monitor("A", "600000", 10.0)
    store = FakeStore(
        dates={"HK": "2026-08-20", "A": "2026-08-20"},
        closes={"A": {"600000.SH": 9.0}},
        failures={("HK", "close")},
    )

    assert evaluate_stock_price_monitors("2026-08-21", connection=connection, store=store) == 1
    assert repo.get_stock_monitor(failed.id).state == "armed"
    assert repo.get_stock_monitor(healthy.id).state == "triggered"
