import sqlite3

import pytest

from services.portfolio.account_service import AccountService
from services.portfolio.db import init_db
from services.portfolio.repository import AccountRepository
from services.backtest.task_manager import TaskManager
from services.portfolio.db import get_connection
from services.db_schema import init_backtest_tables


class FakeTaskManager:
    def __init__(self, tasks):
        self.tasks = tasks
        self.set_calls = []
        self.clear_calls = []

    def get_result(self, task_id):
        return self.tasks.get(task_id)

    def set_execution_account(self, task_id, account_id, connection=None):
        self.set_calls.append((task_id, account_id))
        assert connection is not None
        return {"task_id": task_id, "execution_status": "active", "execution_account_id": account_id}

    def clear_execution_account(self, task_id, connection=None):
        self.clear_calls.append(task_id)
        assert connection is not None
        return {"task_id": task_id, "execution_status": "inactive", "execution_account_id": None}


@pytest.fixture
def service():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    tasks = {
        "success": {"task_id": "success", "status": "success", "execution_status": "inactive"},
        "running": {"task_id": "running", "status": "running", "execution_status": "inactive"},
        "active": {"task_id": "active", "status": "success", "execution_status": "active", "execution_account_id": 99},
    }
    tm = FakeTaskManager(tasks)
    repo = AccountRepository(conn)
    service = AccountService(repo, tm, target_materializer=lambda **kwargs: None)
    yield service, repo, tm
    conn.close()


def test_new_account_defaults_to_unbound(service):
    svc, _, _ = service

    account = svc.create_account("策略账户", "A", "CNY", None)

    assert account.strategy_task_id is None
    assert account.strategy_bound_at is None
    assert account.strategy_unbound_at is None


def test_account_schema_is_idempotent_and_shared_tables_are_preserved(service):
    _, repo, _ = service

    from services.db_schema import init_portfolio_v1_tables

    init_portfolio_v1_tables(repo.conn)
    init_portfolio_v1_tables(repo.conn)
    tables = {
        row[0]
        for row in repo.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "backtest_tasks" in tables
    assert "chat_sessions" in tables
    assert "portfolio_accounts" in tables
    assert "portfolios" not in tables


def test_schema_migration_archives_duplicate_current_states_and_is_rerunnable(service):
    _, repo, _ = service
    from services.db_schema import init_portfolio_v1_tables

    account = repo.create_account("迁移", "A", "CNY")
    repo.conn.execute("DROP INDEX uq_portfolio_current_target")
    repo.conn.execute("DROP INDEX uq_portfolio_current_alert")
    repo.conn.execute(
        "INSERT INTO portfolio_strategy_targets (account_id, symbol, target_quantity, reference_price, status, effective_date, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account.id, "600519.SH", 10, 100, "active", "2026-08-20", "2026-08-20T10:00:00"),
    )
    repo.conn.execute(
        "INSERT INTO portfolio_strategy_targets (account_id, symbol, target_quantity, reference_price, status, effective_date, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account.id, "600519.SH", 20, 110, "active", "2026-08-21", "2026-08-21T10:00:00"),
    )
    repo.conn.execute(
        "INSERT INTO portfolio_strategy_alerts (account_id, symbol, state, updated_at) VALUES (?, ?, ?, ?)",
        (account.id, "600519.SH", "armed", "2026-08-20T10:00:00"),
    )
    repo.conn.execute(
        "INSERT INTO portfolio_strategy_alerts (account_id, symbol, state, updated_at) VALUES (?, ?, ?, ?)",
        (account.id, "600519.SH", "triggered", "2026-08-21T10:00:00"),
    )
    repo.conn.commit()

    init_portfolio_v1_tables(repo.conn)
    first_state = repo.conn.execute(
        "SELECT id, archived_at FROM portfolio_strategy_targets ORDER BY id"
    ).fetchall()
    first_alert_state = repo.conn.execute(
        "SELECT id, archived_at FROM portfolio_strategy_alerts ORDER BY id"
    ).fetchall()

    assert first_state[0]["archived_at"] is not None
    assert first_state[1]["archived_at"] is None
    assert first_alert_state[0]["archived_at"] is not None
    assert first_alert_state[1]["archived_at"] is None

    init_portfolio_v1_tables(repo.conn)
    assert [tuple(row) for row in first_state] == [
        tuple(row)
        for row in repo.conn.execute("SELECT id, archived_at FROM portfolio_strategy_targets ORDER BY id")
    ]
    assert [tuple(row) for row in first_alert_state] == [
        tuple(row)
        for row in repo.conn.execute("SELECT id, archived_at FROM portfolio_strategy_alerts ORDER BY id")
    ]


def test_materializer_receives_the_application_connection(service):
    svc, _, tm = service
    calls = []
    svc.target_materializer = lambda **kwargs: calls.append(kwargs)

    account = svc.create_account("物化调用", "A", "CNY", "success")

    assert calls == [{"account_id": account.id, "task_id": "success", "connection": svc.repository.conn}]
    assert tm.set_calls == [("success", account.id)]


def test_binding_rejects_account_with_current_holdings(service):
    svc, repo, _ = service
    account = svc.create_account("有持仓", "A", "CNY", None)
    repo.add_trade(account.id, "600519.SH", "buy", 100, 10, "2026-08-20")

    with pytest.raises(ValueError, match="current holdings"):
        svc.bind_strategy(account.id, "success")


@pytest.mark.parametrize("task_id", ["running", "active", "missing"])
def test_binding_requires_successful_inactive_unlinked_task(service, task_id):
    svc, _, _ = service

    account = svc.create_account("账户", "A", "CNY", None)

    with pytest.raises(ValueError):
        svc.bind_strategy(account.id, task_id)


def test_binding_is_one_to_one_and_unbinding_preserves_trades(service):
    svc, repo, tm = service
    first = svc.create_account("一", "A", "CNY", None)
    second = svc.create_account("二", "A", "CNY", None)
    svc.bind_strategy(first.id, "success")
    with pytest.raises(ValueError, match="already linked"):
        svc.bind_strategy(second.id, "success")

    repo.add_trade(first.id, "600519.SH", "buy", 100, 10, "2026-08-20")
    unbound = svc.unbind_strategy(first.id)

    assert unbound.strategy_task_id is None
    assert len(repo.list_trades(first.id)) == 1
    assert tm.clear_calls == ["success"]


def test_create_account_can_bind_successful_task(service):
    svc, _, tm = service
    tm.tasks["success-2"] = {"task_id": "success-2", "status": "success", "execution_status": "inactive"}

    account = svc.create_account("直接绑定", "HK", "HKD", "success-2")

    assert account.strategy_task_id == "success-2"
    assert tm.set_calls == [("success-2", account.id)]


def test_default_materializer_fails_closed(service):
    svc, _, _ = service
    account = svc.create_account("无物化器", "A", "CNY", None)
    from services.portfolio.account_service import materialize_strategy_targets

    svc.target_materializer = materialize_strategy_targets

    with pytest.raises(RuntimeError, match="materializer"):
        svc.bind_strategy(account.id, "success")


def test_binding_rolls_back_task_and_account_together(service):
    svc, repo, tm = service
    account = svc.create_account("回滚", "A", "CNY", None)
    svc.target_materializer = lambda **kwargs: None
    original_set_strategy = repo.set_strategy
    repo.set_strategy = lambda *args: (_ for _ in ()).throw(RuntimeError("account write failed"))

    with pytest.raises(RuntimeError, match="account write failed"):
        svc.bind_strategy(account.id, "success")

    assert repo.get_account(account.id).strategy_task_id is None
    assert tm.set_calls == [("success", account.id)]

    repo.set_strategy = original_set_strategy


def test_current_target_and_alert_are_unique(service):
    _, repo, _ = service
    account = repo.create_account("唯一", "A", "CNY")
    repo.conn.execute(
        "INSERT INTO portfolio_strategy_targets (account_id, symbol, target_quantity, reference_price, status, effective_date, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account.id, "600519.SH", 10, 100, "active", "2026-08-20", "2026-08-20T00:00:00"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "INSERT INTO portfolio_strategy_targets (account_id, symbol, target_quantity, reference_price, status, effective_date, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account.id, "600519.SH", 20, 110, "active", "2026-08-21", "2026-08-21T00:00:00"),
        )

    repo.conn.execute(
        "INSERT INTO portfolio_strategy_alerts (account_id, symbol, state, updated_at) VALUES (?, ?, ?, ?)",
        (account.id, "600519.SH", "armed", "2026-08-20T00:00:00"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "INSERT INTO portfolio_strategy_alerts (account_id, symbol, state, updated_at) VALUES (?, ?, ?, ?)",
            (account.id, "600519.SH", "triggered", "2026-08-21T00:00:00"),
        )


def test_real_task_manager_rolls_back_bind_on_account_failure(tmp_path):
    db_path = tmp_path / "portfolio.db"
    conn = get_connection(db_path)
    init_db(conn)
    init_backtest_tables(conn)
    conn.execute(
        "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, created_at) VALUES (?, ?, ?, ?, ?)",
        ("real-task", "success", "screener", "{}", "2026-08-20T00:00:00"),
    )
    conn.commit()
    task_manager = TaskManager(db_path=str(db_path))
    repo = AccountRepository(conn)
    service = AccountService(repo, task_manager, target_materializer=lambda **kwargs: None)
    account = service.create_account("原子绑定", "A", "CNY", None)
    repo.set_strategy = lambda *args: (_ for _ in ()).throw(RuntimeError("account write failed"))

    with pytest.raises(RuntimeError, match="account write failed"):
        service.bind_strategy(account.id, "real-task")

    assert repo.get_account(account.id).strategy_task_id is None
    assert task_manager.get_result("real-task")["execution_status"] == "inactive"
    conn.close()


def test_real_task_manager_rolls_back_unbind_on_account_failure(tmp_path):
    db_path = tmp_path / "portfolio.db"
    conn = get_connection(db_path)
    init_db(conn)
    init_backtest_tables(conn)
    conn.execute(
        "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, created_at) VALUES (?, ?, ?, ?, ?)",
        ("real-task", "success", "screener", "{}", "2026-08-20T00:00:00"),
    )
    conn.commit()
    task_manager = TaskManager(db_path=str(db_path))
    repo = AccountRepository(conn)
    service = AccountService(repo, task_manager, target_materializer=lambda **kwargs: None)
    account = service.create_account("原子解绑", "A", "CNY", None)
    account = service.bind_strategy(account.id, "real-task")
    repo.clear_strategy = lambda *args: (_ for _ in ()).throw(RuntimeError("account write failed"))

    with pytest.raises(RuntimeError, match="account write failed"):
        service.unbind_strategy(account.id)

    assert repo.get_account(account.id).strategy_task_id == "real-task"
    assert task_manager.get_result("real-task")["execution_status"] == "active"
    conn.close()
