import sqlite3

import pytest

from services.portfolio.account_service import AccountService
from services.portfolio.db import init_db
from services.portfolio.repository import AccountRepository


class FakeTaskManager:
    def __init__(self, tasks):
        self.tasks = tasks
        self.set_calls = []
        self.clear_calls = []

    def get_result(self, task_id):
        return self.tasks.get(task_id)

    def set_execution_account(self, task_id, account_id):
        self.set_calls.append((task_id, account_id))
        return {"task_id": task_id, "execution_status": "active", "execution_account_id": account_id}

    def clear_execution_account(self, task_id):
        self.clear_calls.append(task_id)
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


def test_account_schema_is_idempotent_and_separate_from_legacy_tables(service):
    _, repo, _ = service

    from services.db_schema import init_portfolio_v1_tables

    repo.conn.execute("CREATE TABLE backtest_tasks (task_id TEXT PRIMARY KEY)")
    repo.conn.execute("CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY)")
    init_portfolio_v1_tables(repo.conn)
    tables = {
        row[0]
        for row in repo.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "portfolios" in tables
    assert "backtest_tasks" in tables
    assert "chat_sessions" in tables
    assert "portfolio_accounts" in tables


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
