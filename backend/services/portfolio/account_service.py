from datetime import datetime
from typing import Callable

from services.portfolio.models import Account
from services.portfolio.repository import AccountRepository


def materialize_strategy_targets(*, account_id: int, task_id: str, connection):
    """Task 3 seam. Target parsing/materialization is intentionally not implemented here."""


class AccountService:
    def __init__(self, repository: AccountRepository, task_manager, target_materializer: Callable | None = None):
        self.repository = repository
        self.task_manager = task_manager
        self.target_materializer = target_materializer or materialize_strategy_targets

    def create_account(self, name: str, market: str, base_currency: str, strategy_task_id: str | None) -> Account:
        account = self.repository.create_account(name, market, base_currency)
        if strategy_task_id is not None:
            account = self.bind_strategy(account.id, strategy_task_id)
        else:
            self.repository.conn.commit()
        return account

    def bind_strategy(self, account_id: int, task_id: str) -> Account:
        account = self._require_account(account_id)
        if self.repository.current_holdings(account_id):
            raise ValueError("account has current holdings")
        task = self.task_manager.get_result(task_id)
        if not task or task.get("status") != "success":
            raise ValueError("task must be successful")
        if task.get("execution_status") == "active":
            raise ValueError("task is already active")
        linked = self.repository.conn.execute(
            "SELECT id FROM portfolio_accounts WHERE strategy_task_id = ? AND id != ? AND is_active = 1",
            (task_id, account_id),
        ).fetchone()
        if linked:
            raise ValueError("task is already linked to another account")
        if account.strategy_task_id is not None and account.strategy_task_id != task_id:
            raise ValueError("account is already linked")
        now = datetime.now().isoformat()
        try:
            self.target_materializer(account_id=account_id, task_id=task_id, connection=self.repository.conn)
            self.task_manager.set_execution_account(task_id, account_id)
            result = self.repository.set_strategy(account_id, task_id, now)
            self.repository.conn.commit()
            return result
        except Exception:
            self.repository.conn.rollback()
            raise

    def unbind_strategy(self, account_id: int) -> Account:
        account = self._require_account(account_id)
        if account.strategy_task_id is None:
            return account
        now = datetime.now().isoformat()
        try:
            self.repository.archive_strategy_state(account_id, now)
            self.task_manager.clear_execution_account(account.strategy_task_id)
            result = self.repository.clear_strategy(account_id, now)
            self.repository.conn.commit()
            return result
        except Exception:
            self.repository.conn.rollback()
            raise

    def get_account(self, account_id: int) -> Account:
        return self._require_account(account_id)

    def list_accounts(self, include_inactive: bool = False) -> list[Account]:
        return self.repository.list_accounts(include_inactive)

    def _require_account(self, account_id: int) -> Account:
        account = self.repository.get_account(account_id)
        if account is None:
            raise ValueError("account not found")
        return account
