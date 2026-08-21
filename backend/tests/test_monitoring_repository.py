import sqlite3

from services.db_schema import init_portfolio_v1_tables
from services.monitoring.models import StockPriceMonitor, StrategyMonitor
from services.monitoring.repository import MonitoringRepository


def make_repository() -> MonitoringRepository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_portfolio_v1_tables(conn)
    return MonitoringRepository(conn)


def test_strategy_monitor_crud_soft_delete_and_run_history():
    repo = make_repository()

    monitor = repo.create_strategy_monitor(
        name="价值策略",
        strategy_class="ValueStrategy",
        filepath="strategies/value.py",
        params={"pe": 15},
        market="A",
        frequency="weekly",
        symbols=["600000"],
        next_run_date="2026-08-24",
    )
    assert isinstance(monitor, StrategyMonitor)
    assert monitor.params == {"pe": 15}
    assert monitor.symbols == ["600000"]
    assert repo.get_strategy_monitor(monitor.id) == monitor

    updated = repo.update_strategy_monitor(monitor.id, name="价值策略 v2", is_active=False)
    assert updated.name == "价值策略 v2"
    assert not updated.is_active
    assert repo.list_strategy_monitors() == []
    assert repo.list_strategy_monitors(include_inactive=True) == [updated]

    run = repo.create_strategy_run(monitor.id, "2026-08-24", task_id="task-1")
    finished = repo.finish_strategy_run(run.id, "success", result={"count": 1})
    assert finished.status == "success"
    assert finished.result == {"count": 1}
    assert repo.list_strategy_runs(monitor.id)[0] == finished

    deleted = repo.soft_delete_strategy_monitor(monitor.id)
    assert not deleted.is_active
    assert repo.get_strategy_monitor(monitor.id) == deleted


def test_stock_monitors_allow_duplicate_symbols_pause_resume_and_soft_delete():
    repo = make_repository()
    first = repo.create_stock_monitor("A", "600000", 10.0, name="浦发")
    second = repo.create_stock_monitor("A", "600000", 12.0)

    assert isinstance(first, StockPriceMonitor)
    assert [m.id for m in repo.list_stock_monitors()] == [second.id, first.id]
    assert repo.get_stock_monitor(first.id).threshold_price == 10.0

    paused = repo.pause_stock_monitor(first.id)
    assert paused.state == "paused"
    assert repo.resume_stock_monitor(first.id).state == "armed"
    updated = repo.update_stock_monitor(first.id, threshold_price=11.0, name="新浦发")
    assert updated.threshold_price == 11.0
    assert updated.name == "新浦发"

    deleted = repo.soft_delete_stock_monitor(first.id)
    assert not deleted.is_active
    assert len(repo.list_stock_monitors()) == 1
    assert len(repo.list_stock_monitors(include_inactive=True)) == 2


def test_claim_price_trigger_is_single_shot_until_rearmed_and_history_survives_delete():
    repo = make_repository()
    monitor = repo.create_stock_monitor("HK", "00005", 100.0)

    assert repo.claim_price_trigger(monitor.id, 99.0, "2026-08-21", "2026-08-21T16:00:00")
    assert not repo.claim_price_trigger(monitor.id, 98.0, "2026-08-22", "2026-08-22T16:00:00")
    assert repo.get_stock_monitor(monitor.id).state == "triggered"
    assert repo.list_stock_events(monitor.id)[0]["status"] == "recorded"

    assert repo.rearm_price_monitor(monitor.id)
    assert repo.claim_price_trigger(monitor.id, 97.0, "2026-08-25", "2026-08-25T16:00:00")
    assert len(repo.list_stock_events(monitor.id)) == 2

    repo.soft_delete_stock_monitor(monitor.id)
    assert len(repo.list_stock_events(monitor.id)) == 2
    assert repo.get_stock_monitor(monitor.id).state == "triggered"
