import sqlite3

from services.db_schema import init_portfolio_v1_tables
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
