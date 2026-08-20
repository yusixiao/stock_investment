import sqlite3

from services.portfolio.buy_opportunity import BuyOpportunityAlert, evaluate_buy_opportunities
from services.portfolio.db import init_db
from services.portfolio.holdings_service import record_trade
from services.portfolio.repository import AccountRepository


class Sink:
    def __init__(self):
        self.alerts = []

    def emit(self, alert: BuyOpportunityAlert):
        self.alerts.append(alert)


class Store:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query_previous_close(self, symbols, as_of_date):
        self.calls.append((symbols, as_of_date))
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


def test_previous_completed_close_emits_only_for_remaining_target():
    conn, account = setup_account()
    sink = Sink()
    store = Store({"A": 99, "B": 101})

    assert evaluate_buy_opportunities("2026-08-20", sink, connection=conn, store=store) == 1
    assert sink.alerts[0].symbol == "A"
    assert sink.alerts[0].valuation_date == "2026-08-20"
    assert store.calls == [(("A", "B"), "2026-08-20")]


def test_below_threshold_is_not_repeated_and_rearms_above_threshold():
    conn, account = setup_account()
    sink = Sink()
    store = Store({"A": 99, "B": 101})

    evaluate_buy_opportunities("2026-08-20", sink, connection=conn, store=store)
    evaluate_buy_opportunities("2026-08-21", sink, connection=conn, store=Store({"A": 98, "B": 101}))
    evaluate_buy_opportunities("2026-08-22", sink, connection=conn, store=Store({"A": 100, "B": 101}))
    evaluate_buy_opportunities("2026-08-23", sink, connection=conn, store=Store({"A": 99, "B": 101}))

    assert [alert.valuation_date for alert in sink.alerts] == ["2026-08-20", "2026-08-23"]


def test_new_target_already_below_threshold_emits_once_after_restart():
    conn, account = setup_account()
    first = Sink()
    evaluate_buy_opportunities("2026-08-20", first, connection=conn, store=Store({"A": 90, "B": 101}))
    restarted = Sink()
    evaluate_buy_opportunities("2026-08-21", restarted, connection=conn, store=Store({"A": 89, "B": 101}))

    assert len(first.alerts) == 1
    assert restarted.alerts == []


def test_over_target_and_zero_target_never_emit():
    conn, account = setup_account()
    record_trade(account.id, "B", "buy", 20, 90, "2026-08-19", connection=conn)
    repo = AccountRepository(conn)
    repo.add_target_history(account.id, "2026-08-20", '{"task_id":"task-1","targets":[{"symbol":"A","target_quantity":0,"reference_price":100,"status":"exited"},{"symbol":"B","target_quantity":10,"reference_price":100,"status":"active"}]}', "2026-08-20T00:00:00")
    conn.commit()

    sink = Sink()
    assert evaluate_buy_opportunities("2026-08-21", sink, connection=conn, store=Store({"A": 90, "B": 80})) == 0
    assert sink.alerts == []
