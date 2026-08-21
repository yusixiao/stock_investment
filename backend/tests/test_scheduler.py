import builtins
from unittest.mock import MagicMock

import pandas as pd

import scheduler


def test_successful_refresh_calls_buy_opportunity_seam(monkeypatch):
    seam = MagicMock()
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", seam)

    record = MagicMock(status="completed", market_states={
        "A": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}},
        "HK": {"update": {"status": "failed"}, "view": {"status": "success"}, "cache": {"status": "success"}},
        "US": {"update": {"status": "success"}, "view": {"status": "failed"}, "cache": {"status": "success"}},
    })
    scheduler._on_market_refresh_complete(record)

    seam.assert_called_once_with(record, {"A"})


def test_partial_refresh_does_not_call_buy_opportunity_seam(monkeypatch):
    seam = MagicMock()
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", seam)

    record = MagicMock(status="partial", market_states={})
    scheduler._on_market_refresh_complete(record)

    seam.assert_not_called()


def test_partial_refresh_runs_monitors_for_successful_market(monkeypatch):
    buy = MagicMock()
    strategy = MagicMock(return_value=1)
    stock = MagicMock(return_value=1)
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", buy)
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.run_due_strategy_monitors", strategy
    )
    monkeypatch.setattr(
        "services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", stock
    )

    record = MagicMock(status="partial", market_states={
        "A": {"update": {"status": "failed"}, "view": {"status": "failed"}, "cache": {"status": "failed"}},
        "HK": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}},
    })

    scheduler._on_market_refresh_complete(record)

    buy.assert_called_once_with(record, {"HK"})
    strategy.assert_called_once()
    stock.assert_called_once()
    assert strategy.call_args.kwargs["markets"] == {"HK"}
    assert stock.call_args.kwargs["markets"] == {"HK"}


def test_completed_record_with_derived_failure_does_not_evaluate_failed_market(monkeypatch):
    seam = MagicMock()
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", seam)
    record = MagicMock(status="completed", market_states={
        "A": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "failed"}},
        "HK": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}},
    })

    scheduler._on_market_refresh_complete(record)

    seam.assert_called_once_with(record, {"HK"})


def test_snapshot_job_closes_connection_when_init_db_fails(monkeypatch):
    store = MagicMock()
    store.query.side_effect = [
        pd.DataFrame([{"_symbol": "600519.SH", "date": "2026-08-19", "close": 1500.0}]),
        pd.DataFrame(),
        pd.DataFrame(),
    ]
    connection = MagicMock()
    init_db = MagicMock(side_effect=RuntimeError("schema init failed"))
    monkeypatch.setattr("services.market_data.duckdb_store.get_store", lambda: store)
    monkeypatch.setattr("services.portfolio.db.get_connection", lambda: connection)
    monkeypatch.setattr("services.portfolio.db.init_db", init_db)

    try:
        scheduler._snapshot_job()
    except RuntimeError as exc:
        assert str(exc) == "schema init failed"
    else:
        raise AssertionError("snapshot job should propagate init_db failure")

    connection.close.assert_called_once_with()


def test_snapshot_job_continues_other_markets_when_one_view_fails(monkeypatch):
    store = MagicMock()
    store.query.side_effect = [
        RuntimeError("A view missing"),
        pd.DataFrame([{"_symbol": "00005.HK", "date": "2026-08-19", "close": 300.0}]),
        pd.DataFrame([{"_symbol": "AAPL.US", "date": "2026-08-18", "close": 200.0}]),
    ]
    connection = MagicMock()
    monkeypatch.setattr("services.market_data.duckdb_store.get_store", lambda: store)
    monkeypatch.setattr("services.portfolio.db.get_connection", lambda: connection)
    monkeypatch.setattr("services.portfolio.db.init_db", MagicMock())
    snapshot = MagicMock()
    monkeypatch.setattr("services.portfolio.holdings_service.take_all_snapshots", snapshot)

    scheduler._snapshot_job()

    snapshot.assert_called_once_with(
        {"HK": ("2026-08-19", {"00005.HK": 300.0}), "US": ("2026-08-18", {"AAPL.US": 200.0})},
        connection=connection,
    )
    connection.close.assert_called_once_with()


def test_evaluator_isolates_market_failures(monkeypatch, caplog):
    calls = []

    def evaluate(_as_of_date, _sink, *, markets):
        calls.append(markets)
        if markets == {"A"}:
            raise RuntimeError("A evaluator failed")

    monkeypatch.setattr(
        "services.portfolio.buy_opportunity.evaluate_buy_opportunities", evaluate
    )

    scheduler._evaluate_buy_opportunities_after_refresh(
        MagicMock(), {"A", "HK", "US"}
    )

    assert {frozenset(markets) for markets in calls} == {
        frozenset({"A"}), frozenset({"HK"}), frozenset({"US"})
    }
    assert "market=A" in caplog.text


def test_evaluator_import_failure_isolated_to_market_iteration(monkeypatch, caplog):
    real_import = builtins.__import__

    def fail_buy_opportunity_import(name, *args, **kwargs):
        if name == "services.portfolio.buy_opportunity":
            raise ImportError("notification service unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_buy_opportunity_import)

    scheduler._evaluate_buy_opportunities_after_refresh(
        MagicMock(), {"A", "HK", "US"}
    )

    assert caplog.text.count("buy opportunity evaluation failed for market=") == 3


def test_completed_refresh_runs_both_monitor_callbacks_for_ready_markets(monkeypatch):
    strategy = MagicMock(return_value=2)
    stock = MagicMock(return_value=3)
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.run_due_strategy_monitors", strategy
    )
    monkeypatch.setattr(
        "services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", stock
    )
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", MagicMock())

    record = MagicMock(status="completed", market_states={
        "A": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}},
        "HK": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}, "result": {"status": "ready"}},
        "US": {"update": {"status": "failed"}, "view": {"status": "success"}, "cache": {"status": "success"}},
    })

    scheduler._on_market_refresh_complete(record)

    assert {frozenset(call.kwargs["markets"]) for call in strategy.call_args_list} == {
        frozenset({market}) for market in ("A", "HK")
    }
    assert {frozenset(call.kwargs["markets"]) for call in stock.call_args_list} == {
        frozenset({market}) for market in ("A", "HK")
    }
    assert all(call.args[0] for call in strategy.call_args_list)
    assert all(call.args[0] for call in stock.call_args_list)


def test_strategy_monitor_failure_does_not_prevent_stock_monitor_evaluation(monkeypatch, caplog):
    strategy = MagicMock(side_effect=RuntimeError("strategy failed"))
    stock = MagicMock(return_value=1)
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.run_due_strategy_monitors", strategy
    )
    monkeypatch.setattr(
        "services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", stock
    )
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", MagicMock())

    record = MagicMock(status="completed", market_states={
        "A": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}},
    })

    scheduler._on_market_refresh_complete(record)

    strategy.assert_called_once()
    stock.assert_called_once()
    assert "strategy monitor scheduling failed for market=A" in caplog.text


def test_monitor_failure_isolated_to_market(monkeypatch, caplog):
    strategy_calls = []
    stock_calls = []

    def run_strategy(as_of_date, *, markets):
        strategy_calls.append(markets)
        if markets == {"A"}:
            raise RuntimeError("A strategy failed")

    def evaluate_stock(as_of_date, *, markets):
        stock_calls.append(markets)
        if markets == {"HK"}:
            raise RuntimeError("HK stock failed")

    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.run_due_strategy_monitors", run_strategy
    )
    monkeypatch.setattr(
        "services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", evaluate_stock
    )
    monkeypatch.setattr(scheduler, "_evaluate_buy_opportunities_after_refresh", MagicMock())

    record = MagicMock(status="completed", market_states={
        market: {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}}
        for market in ("A", "HK", "US")
    })

    scheduler._on_market_refresh_complete(record)

    assert {frozenset(markets) for markets in strategy_calls} == {
        frozenset({"A"}), frozenset({"HK"}), frozenset({"US"})
    }
    assert {frozenset(markets) for markets in stock_calls} == {
        frozenset({"A"}), frozenset({"HK"}), frozenset({"US"})
    }
    assert "strategy monitor scheduling failed for market=A" in caplog.text
    assert "stock price monitor evaluation failed for market=HK" in caplog.text
