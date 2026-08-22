import json
import sqlite3

import pytest

from services.db_schema import init_backtest_tables
from services.portfolio.db import init_db
from services.portfolio.repository import AccountRepository
from services.portfolio.account_service import AccountService
from services.portfolio.strategy_targets import (
    TargetRecommendationUnavailable,
    get_current_targets,
    get_target_history,
    is_buy_allowed,
    materialize_targets,
)


TASK_ID = "2baab97c"
TARGET_TRADES = [
    {"date": "2026-06-02", "symbol": "000001.SZ", "direction": "buy", "shares": 12200, "price": 89.2281},
    {"date": "2026-06-02", "symbol": "000002.SZ", "direction": "buy", "shares": 28200, "price": 39.38361},
    {"date": "2026-06-02", "symbol": "600000.SH", "direction": "buy", "shares": 202500, "price": 5.39406},
    {"date": "2026-06-02", "symbol": "600519.SH", "direction": "buy", "shares": 29700, "price": 37.53015},
    {"date": "2026-06-02", "symbol": "601318.SH", "direction": "buy", "shares": 41300, "price": 26.04528},
    {"date": "2026-06-03", "symbol": "601318.SH", "direction": "sell", "shares": 41300, "price": 27.0},
    {"date": "2099-01-01", "symbol": "600519.SH", "direction": "sell", "shares": 29700, "price": 40.0},
]


@pytest.fixture
def target_context(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    init_backtest_tables(conn)
    account = AccountRepository(conn).create_account("策略账户", "A", "CNY")
    from services.portfolio import strategy_targets

    monkeypatch.setattr(
        strategy_targets,
        "task_manager",
         type("TaskManager", (), {"get_result": lambda self, task_id, connection=None: {
            "task_id": task_id, "status": "success", "result": {"raw_trades": TARGET_TRADES}
        }})(),
    )
    yield conn, account
    conn.close()


def test_materializer_persists_five_targets_and_history(target_context):
    conn, account = target_context

    assert materialize_targets(account.id, TASK_ID, connection=conn) == 5

    targets = get_current_targets(account.id, "2026-08-20", connection=conn)
    expected = {
        trade["symbol"]: (trade["shares"], trade["price"])
        for trade in TARGET_TRADES[:5]
    }
    expected["601318.SH"] = (0, expected["601318.SH"][1])
    assert {t.symbol: (t.target_quantity, t.reference_price) for t in targets} == expected
    history = get_target_history(account.id, connection=conn)
    assert len(history) == 7
    assert history[0].effective_date == "2026-06-02"
    assert history[-1].effective_date == "2099-01-01"


def test_current_targets_ignore_future_revision_and_zero_quantity_disallows_buy(target_context):
    conn, account = target_context
    materialize_targets(account.id, TASK_ID, connection=conn)

    assert [t.symbol for t in get_current_targets(account.id, "2026-08-20", connection=conn)] == [
        trade["symbol"] for trade in TARGET_TRADES[:5]
    ]
    assert not is_buy_allowed(account.id, "601318.SH", "2026-08-20", connection=conn)
    assert not is_buy_allowed(account.id, "600519.SH", "2099-01-01", connection=conn)
    assert not is_buy_allowed(account.id, "999999.SZ", "2026-08-20", connection=conn)


def test_materializer_rejects_result_without_explicit_recommendations(target_context):
    conn, account = target_context
    from services.portfolio import strategy_targets
    strategy_targets.task_manager.get_result = lambda task_id, connection=None: {
        "task_id": task_id, "status": "success", "result": {"trades": []}
    }

    with pytest.raises(TargetRecommendationUnavailable):
        materialize_targets(account.id, TASK_ID, connection=conn)


@pytest.mark.parametrize("bad_trade", [
    {"date": "2026-6-2", "symbol": "A", "direction": "buy", "shares": 1, "price": 1},
    {"date": "2026-06-02", "symbol": "A", "direction": "buy", "shares": 1.5, "price": 1},
    {"date": "2026-06-02", "symbol": "A", "direction": "buy", "shares": 1, "price": float("nan")},
])
def test_raw_trade_contract_rejects_invalid_values(target_context, bad_trade):
    from services.portfolio import strategy_targets
    strategy_targets.task_manager.get_result = lambda task_id, connection=None: {
        "task_id": task_id, "status": "success", "result": {"raw_trades": [bad_trade]}
    }

    with pytest.raises(TargetRecommendationUnavailable):
        materialize_targets(target_context[1].id, TASK_ID, connection=target_context[0])


def test_raw_trade_contract_orders_same_day_trades_and_zeroes_partial_sell(target_context):
    conn, account = target_context
    from services.portfolio import strategy_targets
    strategy_targets.task_manager.get_result = lambda task_id, connection=None: {
        "task_id": task_id,
        "status": "success",
        "result": {"raw_trades": [
            {"date": "2026-06-02", "symbol": "A", "direction": "buy", "shares": 10, "price": 10},
            {"date": "2026-06-02", "symbol": "A", "direction": "buy", "shares": 12, "price": 11},
            {"date": "2026-06-03", "symbol": "A", "direction": "sell", "shares": 1, "price": 12},
        ]},
    }

    materialize_targets(account.id, TASK_ID, connection=conn)
    revisions = get_target_history(account.id, connection=conn)
    assert [(revision.effective_date, revision.targets[0].target_quantity, revision.targets[0].reference_price) for revision in revisions] == [
        ("2026-06-02", 10, 10.0),
        ("2026-06-02", 12, 11.0),
        ("2026-06-03", 0, 11.0),
    ]


def test_raw_trade_contract_ignores_liquidation_of_preexisting_position(target_context):
    conn, account = target_context
    from services.portfolio import strategy_targets

    strategy_targets.task_manager.get_result = lambda task_id, connection=None: {
        "task_id": task_id,
        "status": "success",
        "result": {"raw_trades": [
            {"date": "2026-06-02", "symbol": "OLD", "direction": "sell", "shares": 100, "price": 9},
            {"date": "2026-06-02", "symbol": "TARGET", "direction": "buy", "shares": 10, "price": 10},
        ]},
    }

    assert materialize_targets(account.id, TASK_ID, connection=conn) == 1
    targets = get_current_targets(account.id, "2026-08-20", connection=conn)
    assert [(target.symbol, target.target_quantity) for target in targets] == [("TARGET", 10)]


@pytest.mark.parametrize(
    ("trades", "message"),
    [
        (
            [{"date": "2026-06-02", "symbol": "A", "direction": "sell", "shares": 1, "price": 9}],
            "no buy target recommendations",
        ),
    ],
)
def test_raw_trade_contract_rejects_invalid_sell_sequences(target_context, trades, message):
    conn, account = target_context
    from services.portfolio import strategy_targets

    strategy_targets.task_manager.get_result = lambda task_id, connection=None: {
        "task_id": task_id, "status": "success", "result": {"raw_trades": trades}
    }

    with pytest.raises(TargetRecommendationUnavailable, match=message):
        materialize_targets(account.id, TASK_ID, connection=conn)


def test_raw_trade_contract_treats_oversized_sell_as_strategy_exit(target_context):
    conn, account = target_context
    from services.portfolio import strategy_targets

    strategy_targets.task_manager.get_result = lambda task_id, connection=None: {
        "task_id": task_id,
        "status": "success",
        "result": {"raw_trades": [
            {"date": "2026-06-02", "symbol": "A", "direction": "buy", "shares": 2, "price": 10},
            {"date": "2026-06-03", "symbol": "A", "direction": "sell", "shares": 3, "price": 9},
        ]},
    }

    materialize_targets(account.id, TASK_ID, connection=conn)
    targets = get_current_targets(account.id, "2026-08-20", connection=conn)
    assert [(target.symbol, target.target_quantity, target.status) for target in targets] == [("A", 0, "exited")]
