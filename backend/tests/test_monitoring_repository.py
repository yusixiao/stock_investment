import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.db_schema import init_monitoring_tables
from services.monitoring.models import StockPriceMonitor, StrategyMonitor
from services.monitoring.repository import MonitoringRepository


def make_repository() -> MonitoringRepository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_monitoring_tables(conn)
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
    with pytest.raises(ValueError):
        repo.pause_stock_monitor(first.id)
    with pytest.raises(ValueError):
        repo.resume_stock_monitor(first.id)
    assert repo.get_stock_monitor(first.id).state == "armed"
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


def test_monitoring_rejects_invalid_enum_values():
    repo = make_repository()

    with pytest.raises(ValueError):
        repo.create_strategy_monitor("bad", "Strategy", "x.py", {}, "A", "yearly")
    strategy = repo.create_strategy_monitor("ok", "Strategy", "x.py", {}, "A", "daily")
    with pytest.raises(ValueError):
        repo.update_strategy_monitor(strategy.id, frequency="yearly")

    stock = repo.create_stock_monitor("A", "600000", 10)
    with pytest.raises(ValueError):
        repo.update_stock_monitor(stock.id, state="unknown")
    with pytest.raises(ValueError):
        repo.finish_strategy_run(repo.create_strategy_run(strategy.id, "2026-08-21").id, "running")

    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "INSERT INTO monitoring_strategy_monitors (name, strategy_class, filepath, params, market, frequency, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("bad", "Strategy", "x.py", "{}", "A", "yearly", "now", "now"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "INSERT INTO monitoring_strategy_runs (monitor_id, scheduled_date, started_at, status) VALUES (?, ?, ?, ?)",
            (strategy.id, "2026-08-21", "now", "unknown"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "INSERT INTO monitoring_stock_monitors (market, symbol, threshold_price, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("A", "600000", 10, "unknown", "now", "now"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "INSERT INTO monitoring_stock_events (monitor_id, market, symbol, observed_price, threshold_price, observed_date, triggered_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (stock.id, "A", "600000", 9, 10, "2026-08-21", "2026-08-21T16:00:00", "unknown"),
        )


def test_finish_strategy_run_is_terminal_and_does_not_overwrite_latest_monitor_status():
    repo = make_repository()
    monitor = repo.create_strategy_monitor("strategy", "Strategy", "x.py", {}, "A", "daily")
    run = repo.create_strategy_run(monitor.id, "2026-08-21")
    newer_run = repo.create_strategy_run(monitor.id, "2026-08-22")

    newer_finished = repo.finish_strategy_run(newer_run.id, "success", result={"value": 2})
    assert newer_finished.status == "success"
    older_finished = repo.finish_strategy_run(run.id, "failed", error="old failure")
    assert older_finished.status == "failed"
    with pytest.raises(ValueError):
        repo.finish_strategy_run(run.id, "failed", error="late result")
    assert repo.list_strategy_runs(monitor.id)[0] == newer_finished
    assert repo.get_strategy_monitor(monitor.id).last_run_status == "success"


def test_claim_price_trigger_is_idempotent_across_two_connections(tmp_path: Path):
    db_path = tmp_path / "monitoring.db"
    seed = sqlite3.connect(db_path)
    seed.row_factory = sqlite3.Row
    init_monitoring_tables(seed)
    monitor = MonitoringRepository(seed).create_stock_monitor("US", "AAPL", 100)
    seed.commit()
    seed.close()

    connections = []
    for _ in range(2):
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        connections.append(conn)

    def claim(index: int) -> bool:
        return MonitoringRepository(connections[index]).claim_price_trigger(
            monitor.id, 99, "2026-08-21", "2026-08-21T16:00:00"
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, (0, 1)))

    assert sorted(results) == [False, True]
    check = sqlite3.connect(db_path)
    assert check.execute("SELECT COUNT(*) FROM monitoring_stock_events").fetchone()[0] == 1


def test_init_migrates_existing_monitoring_tables_and_preserves_rows():
    conn = sqlite3.connect(":memory:")
    init_monitoring_tables(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in (
        "monitoring_strategy_monitors",
        "monitoring_strategy_runs",
        "monitoring_stock_monitors",
        "monitoring_stock_events",
    ):
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}_checked")
    conn.executescript(
        """
        CREATE TABLE monitoring_strategy_monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            strategy_class TEXT NOT NULL, filepath TEXT NOT NULL,
            params TEXT NOT NULL DEFAULT '{}', market TEXT NOT NULL,
            frequency TEXT NOT NULL, symbols TEXT, is_active INTEGER NOT NULL DEFAULT 1,
            next_run_date TEXT, last_run_at TEXT, last_run_status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE monitoring_strategy_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, monitor_id INTEGER NOT NULL,
            scheduled_date TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
            status TEXT NOT NULL, task_id TEXT, result TEXT, error TEXT
        );
        CREATE TABLE monitoring_stock_monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, market TEXT NOT NULL, symbol TEXT NOT NULL,
            name TEXT, threshold_price REAL NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
            state TEXT NOT NULL DEFAULT 'armed', last_price REAL, last_price_date TEXT,
            last_triggered_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE monitoring_stock_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, monitor_id INTEGER NOT NULL,
            market TEXT NOT NULL, symbol TEXT NOT NULL, observed_price REAL NOT NULL,
            threshold_price REAL NOT NULL, observed_date TEXT NOT NULL,
            triggered_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'recorded'
        );
        INSERT INTO monitoring_strategy_monitors
            (id, name, strategy_class, filepath, params, market, frequency, symbols, created_at, updated_at)
            VALUES (7, 'old', 'Strategy', 'old.py', '{}', 'A', 'daily', NULL, 'now', 'now');
        INSERT INTO monitoring_strategy_runs
            (id, monitor_id, scheduled_date, started_at, status)
            VALUES (8, 7, '2026-08-21', 'now', 'running');
        INSERT INTO monitoring_stock_monitors
            (id, market, symbol, threshold_price, created_at, updated_at)
            VALUES (9, 'A', '600000', 10, 'now', 'now');
        INSERT INTO monitoring_stock_events
            (id, monitor_id, market, symbol, observed_price, threshold_price, observed_date, triggered_at)
            VALUES (10, 9, 'A', '600000', 9, 10, '2026-08-21', 'now');
        """
    )
    for table in (
        "monitoring_strategy_monitors",
        "monitoring_strategy_runs",
        "monitoring_stock_monitors",
        "monitoring_stock_events",
    ):
        conn.execute(f"DROP TABLE {table}_checked")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")

    init_monitoring_tables(conn)

    assert conn.execute("SELECT id FROM monitoring_strategy_monitors").fetchone()[0] == 7
    assert conn.execute("SELECT id FROM monitoring_strategy_runs").fetchone()[0] == 8
    assert conn.execute("SELECT id FROM monitoring_stock_monitors").fetchone()[0] == 9
    assert conn.execute("SELECT id FROM monitoring_stock_events").fetchone()[0] == 10
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO monitoring_strategy_monitors (name, strategy_class, filepath, market, frequency, created_at, updated_at) VALUES ('bad', 'S', 'x', 'A', 'yearly', 'now', 'now')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO monitoring_strategy_runs (monitor_id, scheduled_date, started_at, status) VALUES (7, '2026-08-21', 'now', 'unknown')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO monitoring_stock_monitors (market, symbol, threshold_price, state, created_at, updated_at) VALUES ('A', '600001', 10, 'unknown', 'now', 'now')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO monitoring_stock_events (monitor_id, market, symbol, observed_price, threshold_price, observed_date, triggered_at, status) VALUES (9, 'A', '600000', 9, 10, '2026-08-21', 'now', 'unknown')"
        )
