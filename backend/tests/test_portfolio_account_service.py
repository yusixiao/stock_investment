import sqlite3
from concurrent.futures import ThreadPoolExecutor

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

    def get_result(self, task_id, connection=None):
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


def test_binding_rejects_inactive_account(service):
    svc, repo, _ = service
    account = svc.create_account("停用账户", "A", "CNY", None)
    repo.conn.execute("UPDATE portfolio_accounts SET is_active = 0 WHERE id = ?", (account.id,))
    repo.conn.commit()

    with pytest.raises(ValueError, match="account inactive"):
        svc.bind_strategy(account.id, "success")


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


def test_soft_delete_deactivates_account_and_preserves_history(service):
    svc, repo, _ = service
    account = svc.create_account("软删除", "A", "CNY", None)
    repo.add_trade(account.id, "600519.SH", "buy", 100, 10, "2026-08-20")
    repo.add_target_history(account.id, "2026-08-20", "{}", "2026-08-20T00:00:00")

    deleted = svc.soft_delete_account(account.id)

    assert deleted.is_active is False
    assert len(repo.list_trades(account.id)) == 1
    assert len(repo.strategy_target_history(account.id)) == 1
    assert repo.get_account(account.id).is_active is False


def test_soft_delete_rejects_bound_account_without_changing_binding(service):
    svc, repo, _ = service
    account = svc.create_account("绑定账户", "A", "CNY", None)
    svc.bind_strategy(account.id, "success")

    with pytest.raises(ValueError, match="unbind strategy before deleting account"):
        svc.soft_delete_account(account.id)

    assert repo.get_account(account.id).strategy_task_id == "success"
    assert repo.get_account(account.id).is_active is True


def test_soft_delete_rejects_already_inactive_account(service):
    svc, _, _ = service
    account = svc.create_account("重复删除", "A", "CNY", None)
    svc.soft_delete_account(account.id)

    with pytest.raises(ValueError, match="account already inactive"):
        svc.soft_delete_account(account.id)


def test_soft_delete_only_updates_is_active(service):
    svc, repo, _ = service
    account = svc.create_account("只更新状态", "A", "CNY", None)

    deleted = svc.soft_delete_account(account.id)
    row = repo.conn.execute(
        "SELECT is_active, updated_at FROM portfolio_accounts WHERE id = ?", (account.id,)
    ).fetchone()

    assert deleted.updated_at == account.updated_at
    assert row["is_active"] == 0
    assert row["updated_at"] == account.updated_at


def test_soft_delete_begins_immediate_before_loading_account(service):
    svc, repo, _ = service
    account = svc.create_account("先加锁", "A", "CNY", None)
    statements = []
    repo.conn.set_trace_callback(statements.append)

    svc.soft_delete_account(account.id)

    begin_index = next(i for i, sql in enumerate(statements) if "BEGIN IMMEDIATE" in sql.upper())
    select_index = next(i for i, sql in enumerate(statements) if "SELECT * FROM portfolio_accounts" in sql)
    assert begin_index < select_index


def test_soft_delete_maps_zero_row_competition_and_rolls_back(service):
    svc, repo, _ = service
    account = svc.create_account("竞争删除", "A", "CNY", None)

    def competing_delete(*args):
        repo.conn.execute("UPDATE portfolio_accounts SET is_active = 0 WHERE id = ?", (account.id,))
        raise ValueError("account already inactive")

    repo.soft_delete = competing_delete

    with pytest.raises(ValueError, match="account already inactive"):
        svc.soft_delete_account(account.id)

    assert repo.conn.in_transaction is False
    assert repo.get_account(account.id).is_active is True


def test_soft_delete_rolls_back_repository_failure(service):
    svc, repo, _ = service
    account = svc.create_account("删除回滚", "A", "CNY", None)

    def failing_delete(*args):
        repo.conn.execute("UPDATE portfolio_accounts SET is_active = 0 WHERE id = ?", (account.id,))
        raise RuntimeError("delete failed")

    repo.soft_delete = failing_delete

    with pytest.raises(RuntimeError, match="delete failed"):
        svc.soft_delete_account(account.id)

    assert repo.conn.in_transaction is False
    assert repo.get_account(account.id).is_active is True


def test_repository_soft_delete_rejects_zero_row_update(service):
    _, repo, _ = service
    account = repo.create_account("仓储竞争", "A", "CNY")
    repo.conn.execute("UPDATE portfolio_accounts SET is_active = 0 WHERE id = ?", (account.id,))
    repo.conn.commit()

    with pytest.raises(ValueError, match="account already inactive"):
        repo.soft_delete(account.id, "ignored")


def test_create_account_begins_immediate_before_insert_and_rolls_back_bind(service):
    svc, repo, _ = service
    statements = []
    repo.conn.set_trace_callback(statements.append)
    svc.target_materializer = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("materialization failed")
    )

    with pytest.raises(RuntimeError, match="materialization failed"):
        svc.create_account("原子创建", "A", "CNY", "success")

    insert_index = next(i for i, sql in enumerate(statements) if "INSERT INTO portfolio_accounts" in sql)
    assert any("BEGIN IMMEDIATE" in sql.upper() for sql in statements[:insert_index])
    assert repo.conn.execute("SELECT COUNT(*) FROM portfolio_accounts").fetchone()[0] == 0


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


def test_concurrent_bindings_leave_one_account_and_one_task(tmp_path):
    db_path = tmp_path / "concurrent-bind.db"
    seed = sqlite3.connect(db_path)
    seed.row_factory = sqlite3.Row
    init_db(seed)
    init_backtest_tables(seed)
    seed.execute(
        "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, created_at) VALUES (?, 'success', 'screener', '{}', ?)",
        ("race-task", "2026-08-20T00:00:00"),
    )
    repo = AccountRepository(seed)
    first = repo.create_account("一", "A", "CNY")
    second = repo.create_account("二", "A", "CNY")
    seed.commit()
    seed.close()

    class RealTaskManager(TaskManager):
        pass

    def bind(account_id):
        conn = sqlite3.connect(db_path, timeout=2)
        conn.row_factory = sqlite3.Row
        service = AccountService(
            AccountRepository(conn),
            RealTaskManager(db_path=str(db_path)),
            target_materializer=lambda **kwargs: None,
        )
        try:
            service.bind_strategy(account_id, "race-task")
            return "bound"
        except (ValueError, sqlite3.IntegrityError):
            return "rejected"
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(bind, (first.id, second.id)))

    assert sorted(outcomes) == ["bound", "rejected"]
    check = sqlite3.connect(db_path)
    check.row_factory = sqlite3.Row
    assert check.execute("SELECT COUNT(*) FROM portfolio_accounts WHERE strategy_task_id = 'race-task'").fetchone()[0] == 1
    assert check.execute("SELECT COUNT(*) FROM backtest_tasks WHERE execution_status = 'active' AND execution_account_id IS NOT NULL").fetchone()[0] == 1
    check.close()
