import sqlite3
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.portfolio.buy_opportunity import BuyOpportunityAlert, evaluate_buy_opportunities
from services.portfolio.db import init_db
from services.portfolio.db import get_connection
from services.portfolio.holdings_service import record_trade
from services.portfolio.repository import AccountRepository
from services.market_data.duckdb_store import DuckDBStore


class Sink:
    def __init__(self):
        self.alerts = []

    def emit(self, alert: BuyOpportunityAlert):
        self.alerts.append(alert)


class FailingSink(Sink):
    def __init__(self, failed_symbols):
        super().__init__()
        self.failed_symbols = set(failed_symbols)

    def emit(self, alert: BuyOpportunityAlert):
        if alert.symbol in self.failed_symbols:
            raise RuntimeError(f"sink failed for {alert.symbol}")
        super().emit(alert)


class Store:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def previous_trading_date(self, market, before_date):
        valuation_date = (date.fromisoformat(before_date) - timedelta(days=1)).isoformat()
        self.calls.append(("date", market, before_date, valuation_date))
        return valuation_date

    def query_previous_close(self, market, symbols, valuation_date):
        self.calls.append(("close", market, symbols, valuation_date))
        return {symbol: close for symbol, close in self.rows.items() if symbol in symbols}


def setup_account():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    repo = AccountRepository(conn)
    account = repo.create_account("策略账户", "A", "CNY")
    repo.set_strategy(account.id, "task-1", "2026-08-19")
    payload = '{"task_id":"task-1","targets":[{"symbol":"A","target_quantity":10,"reference_price":100,"status":"active"},{"symbol":"B","target_quantity":10,"reference_price":100,"status":"active"}]}'
    repo.add_target_history(account.id, "2026-08-19", payload, "2026-08-19T00:00:00")
    conn.commit()
    return conn, account


def setup_market_account(market, symbol):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    repo = AccountRepository(conn)
    account = repo.create_account(f"{market}策略账户", market, "CNY")
    repo.set_strategy(account.id, "task-1", "2026-08-19")
    repo.add_target_history(account.id, "2026-08-19", '{"task_id":"task-1","targets":[{"symbol":"' + symbol + '","target_quantity":10,"reference_price":100,"status":"active"}]}', "2026-08-19T00:00:00")
    conn.commit()
    return conn, account


def test_previous_completed_close_emits_only_for_remaining_target():
    conn, account = setup_account()
    sink = Sink()
    store = Store({"A": 99, "B": 101})

    assert evaluate_buy_opportunities("2026-08-20", sink, connection=conn, store=store) == 1
    assert sink.alerts[0].symbol == "A"
    assert sink.alerts[0].valuation_date == "2026-08-19"
    assert store.calls == [
        ("date", "A", "2026-08-20", "2026-08-19"),
        ("close", "A", ("A", "B"), "2026-08-19"),
    ]


def test_below_threshold_is_not_repeated_and_rearms_above_threshold():
    conn, account = setup_account()
    sink = Sink()
    store = Store({"A": 99, "B": 101})

    evaluate_buy_opportunities("2026-08-20", sink, connection=conn, store=store)
    evaluate_buy_opportunities("2026-08-21", sink, connection=conn, store=Store({"A": 98, "B": 101}))
    evaluate_buy_opportunities("2026-08-22", sink, connection=conn, store=Store({"A": 100, "B": 101}))
    evaluate_buy_opportunities("2026-08-23", sink, connection=conn, store=Store({"A": 99, "B": 101}))

    assert [alert.valuation_date for alert in sink.alerts] == ["2026-08-19", "2026-08-22"]


def test_new_target_already_below_threshold_emits_once_after_restart():
    conn, account = setup_account()
    first = Sink()
    evaluate_buy_opportunities("2026-08-20", first, connection=conn, store=Store({"A": 90, "B": 101}))
    restarted = Sink()
    evaluate_buy_opportunities("2026-08-21", restarted, connection=conn, store=Store({"A": 89, "B": 101}))

    assert len(first.alerts) == 1
    assert restarted.alerts == []


def test_same_valuation_date_is_idempotent():
    conn, account = setup_account()
    first = Sink()
    second = Sink()
    evaluate_buy_opportunities("2026-08-20", first, connection=conn, store=Store({"A": 90, "B": 101}))
    evaluate_buy_opportunities("2026-08-20", second, connection=conn, store=Store({"A": 90, "B": 101}))

    assert len(first.alerts) == 1
    assert second.alerts == []


def test_sink_failure_does_not_reemit_claimed_alert_on_retry():
    conn, account = setup_account()
    failed = FailingSink({"A"})

    assert evaluate_buy_opportunities("2026-08-20", failed, connection=conn, store=Store({"A": 90, "B": 101})) == 0
    retry = Sink()
    assert evaluate_buy_opportunities("2026-08-20", retry, connection=conn, store=Store({"A": 90, "B": 101})) == 0
    assert retry.alerts == []


def test_sink_failure_in_middle_does_not_repeat_prior_success_on_retry():
    conn, account = setup_account()
    failed = FailingSink({"B"})

    assert evaluate_buy_opportunities("2026-08-20", failed, connection=conn, store=Store({"A": 90, "B": 90})) == 1
    assert [alert.symbol for alert in failed.alerts] == ["A"]
    retry = Sink()
    assert evaluate_buy_opportunities("2026-08-20", retry, connection=conn, store=Store({"A": 90, "B": 90})) == 0
    assert retry.alerts == []


def test_sink_failure_does_not_rollback_external_transaction():
    conn, account = setup_account()
    conn.execute("BEGIN")
    failed = FailingSink({"A"})

    assert evaluate_buy_opportunities("2026-08-20", failed, connection=conn, store=Store({"A": 90, "B": 101})) == 0
    assert conn.in_transaction is True
    conn.commit()
    retry = Sink()
    assert evaluate_buy_opportunities("2026-08-20", retry, connection=conn, store=Store({"A": 90, "B": 101})) == 0


def test_concurrent_evaluators_emit_once_for_same_valuation_date(tmp_path):
    db_path = tmp_path / "portfolio.db"
    conn, account = setup_account()
    conn.close()

    # Recreate the setup in a file-backed database so separate evaluator
    # connections exercise SQLite's transaction lock rather than sharing state.
    conn = get_connection(db_path)
    init_db(conn)
    repo = AccountRepository(conn)
    account = repo.create_account("并发策略账户", "A", "CNY")
    repo.set_strategy(account.id, "task-1", "2026-08-19")
    repo.add_target_history(account.id, "2026-08-19", '{"task_id":"task-1","targets":[{"symbol":"A","target_quantity":10,"reference_price":100,"status":"active"}]}', "2026-08-19T00:00:00")
    conn.commit()
    conn.close()

    sink = Sink()

    def evaluate_once():
        connection = get_connection(db_path)
        try:
            return evaluate_buy_opportunities("2026-08-20", sink, connection=connection, store=Store({"A": 90}))
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: evaluate_once(), range(2)))

    assert sorted(results) == [0, 1]
    assert len(sink.alerts) == 1


def test_repository_claim_is_false_for_same_revision_and_valuation_date():
    conn, account = setup_account()
    repo = AccountRepository(conn)
    payload = '{"revision":"rev-1","valuation_date":"2026-08-19","processed":true}'

    assert repo.claim_alert(account.id, "A", "rev-1", "2026-08-19", payload, "2026-08-19T00:00:00") is True
    assert repo.claim_alert(account.id, "A", "rev-1", "2026-08-19", payload, "2026-08-19T00:01:00") is False


@pytest.mark.parametrize("market,symbol", [("A", "000001.SZ"), ("HK", "00001.HK"), ("US", "AAPL.US")])
def test_evaluator_routes_all_supported_markets(market, symbol):
    conn, account = setup_market_account(market, symbol)
    sink = Sink()
    store = Store({symbol: 90})

    assert evaluate_buy_opportunities("2026-08-20", sink, connection=conn, store=store) == 1
    assert ("date", market, "2026-08-20", "2026-08-19") in store.calls
    assert ("close", market, (symbol,), "2026-08-19") in store.calls


def test_duckdb_store_rejects_unknown_market_before_building_sql():
    store = object.__new__(DuckDBStore)

    with pytest.raises(ValueError, match="market"):
        store.previous_trading_date("CN", "2026-08-20")
    with pytest.raises(ValueError, match="market"):
        store.query_previous_close("CN", ("A",), "2026-08-19")
    with pytest.raises(ValueError, match="market"):
        store.previous_trading_date(None, "2026-08-20")


def test_hk_account_routes_both_date_and_close_queries_to_hk_view():
    conn, account = setup_market_account("HK", "00001.HK")
    sink = Sink()
    store = Store({"00001.HK": 90})

    assert evaluate_buy_opportunities("2026-08-20", sink, connection=conn, store=store) == 1
    assert ("date", "HK", "2026-08-20", "2026-08-19") in store.calls
    assert ("close", "HK", ("00001.HK",), "2026-08-19") in store.calls


def test_changed_target_content_rearms_even_with_same_task_and_effective_date():
    conn, account = setup_account()
    repo = AccountRepository(conn)
    first = Sink()
    evaluate_buy_opportunities("2026-08-20", first, connection=conn, store=Store({"A": 90, "B": 101}))

    repo.add_target_history(account.id, "2026-08-19", '{"task_id":"task-1","targets":[{"symbol":"A","target_quantity":20,"reference_price":110,"status":"active"},{"symbol":"B","target_quantity":10,"reference_price":100,"status":"active"}]}', "2026-08-20T00:00:00")
    conn.commit()
    second = Sink()
    evaluate_buy_opportunities("2026-08-21", second, connection=conn, store=Store({"A": 105, "B": 101}))

    assert len(first.alerts) == 1
    assert len(second.alerts) == 1
    assert second.alerts[0].reference_price == 110


def test_over_target_and_zero_target_never_emit():
    conn, account = setup_account()
    record_trade(account.id, "B", "buy", 20, 90, "2026-08-19", connection=conn)
    repo = AccountRepository(conn)
    repo.add_target_history(account.id, "2026-08-20", '{"task_id":"task-1","targets":[{"symbol":"A","target_quantity":0,"reference_price":100,"status":"exited"},{"symbol":"B","target_quantity":10,"reference_price":100,"status":"active"}]}', "2026-08-20T00:00:00")
    conn.commit()

    sink = Sink()
    assert evaluate_buy_opportunities("2026-08-21", sink, connection=conn, store=Store({"A": 90, "B": 80})) == 0
    assert sink.alerts == []
