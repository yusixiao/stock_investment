import inspect
from unittest.mock import MagicMock

import scheduler


def test_partial_refresh_runs_monitors_for_successful_market(monkeypatch):
    strategy = MagicMock(return_value=1)
    stock = MagicMock(return_value=1)
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

    strategy.assert_called_once()
    stock.assert_called_once()
    assert strategy.call_args.kwargs["markets"] == {"HK"}
    assert stock.call_args.kwargs["markets"] == {"HK"}


def test_completed_record_with_derived_failure_does_not_evaluate_failed_market(monkeypatch):
    strategy = MagicMock()
    stock = MagicMock()
    monkeypatch.setattr("services.monitoring.strategy_monitor.run_due_strategy_monitors", strategy)
    monkeypatch.setattr("services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", stock)
    record = MagicMock(status="completed", market_states={
        "A": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "failed"}},
        "HK": {"update": {"status": "success"}, "view": {"status": "success"}, "cache": {"status": "success"}},
    })

    scheduler._on_market_refresh_complete(record)

    assert [call.kwargs["markets"] for call in strategy.call_args_list] == [{"HK"}]
    assert [call.kwargs["markets"] for call in stock.call_args_list] == [{"HK"}]


def test_refresh_completion_keeps_monitoring_and_drops_portfolio_work(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.run_due_strategy_monitors",
        lambda *args, **kwargs: calls.append("strategy") or 1,
    )
    monkeypatch.setattr(
        "services.monitoring.stock_price_monitor.evaluate_stock_price_monitors",
        lambda *args, **kwargs: calls.append("stock") or 1,
    )

    record = MagicMock(
        status="completed",
        source="scheduler",
        market_states={
            "A": {
                "update": {"status": "success"},
                "view": {"status": "success"},
                "cache": {"status": "success"},
            }
        },
    )
    scheduler._on_market_refresh_complete(record)

    assert calls == ["strategy", "stock"]
    assert not hasattr(scheduler, "_evaluate_buy_opportunities_after_refresh")


def test_completed_refresh_runs_both_monitor_callbacks_for_ready_markets(monkeypatch):
    strategy = MagicMock(return_value=2)
    stock = MagicMock(return_value=3)
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.run_due_strategy_monitors", strategy
    )
    monkeypatch.setattr(
        "services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", stock
    )

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


def test_scheduler_has_no_duplicate_refresh_path():
    source = inspect.getsource(scheduler)

    assert not hasattr(scheduler, "_post_market_update_refresh")
    assert "data_cache.invalidate" not in source
    assert "data_cache.load_market_async" not in source


def test_scheduler_does_not_register_daily_snapshot(monkeypatch):
    add_job = MagicMock()
    monkeypatch.setattr(scheduler.scheduler, "add_job", add_job)
    monkeypatch.setattr(scheduler.scheduler, "start", MagicMock())

    scheduler.start_scheduler()

    registered_ids = {call.kwargs["id"] for call in add_job.call_args_list}
    assert "daily_snapshot" not in registered_ids


def test_completed_refresh_excludes_non_ready_result_from_subscribers(monkeypatch):
    strategy = MagicMock()
    stock = MagicMock()
    monkeypatch.setattr("services.monitoring.strategy_monitor.run_due_strategy_monitors", strategy)
    monkeypatch.setattr("services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", stock)

    record = MagicMock(status="partial", market_states={
        "A": {
            "update": {"status": "success"},
            "view": {"status": "success"},
            "cache": {"status": "success"},
            "result": {"status": "stale"},
        },
        "HK": {
            "update": {"status": "success"},
            "view": {"status": "success"},
            "cache": {"status": "success"},
            "result": {"status": "ready"},
        },
    })

    scheduler._on_market_refresh_complete(record)

    assert [call.kwargs["markets"] for call in strategy.call_args_list] == [{"HK"}]
    assert [call.kwargs["markets"] for call in stock.call_args_list] == [{"HK"}]


def test_strategy_monitor_failure_does_not_prevent_stock_monitor_evaluation(monkeypatch, caplog):
    strategy = MagicMock(side_effect=RuntimeError("strategy failed"))
    stock = MagicMock(return_value=1)
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.run_due_strategy_monitors", strategy
    )
    monkeypatch.setattr(
        "services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", stock
    )

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
