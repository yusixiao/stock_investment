import sqlite3
from datetime import datetime
from typing import cast

from services.portfolio.models import Account


class AccountRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _account(self, row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"], name=row["name"], market=row["market"],
            base_currency=row["base_currency"], strategy_task_id=row["strategy_task_id"],
            strategy_bound_at=row["strategy_bound_at"], strategy_unbound_at=row["strategy_unbound_at"],
            is_active=bool(row["is_active"]), created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def create_account(self, name: str, market: str, base_currency: str) -> Account:
        now = datetime.now().isoformat()
        cur = self.conn.execute(
            "INSERT INTO portfolio_accounts (name, market, base_currency, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, market, base_currency, now, now),
        )
        row = self.conn.execute("SELECT * FROM portfolio_accounts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._account(row)

    def get_account(self, account_id: int) -> Account | None:
        row = self.conn.execute("SELECT * FROM portfolio_accounts WHERE id = ?", (account_id,)).fetchone()
        return self._account(row) if row else None

    def list_accounts(self, include_inactive: bool = False) -> list[Account]:
        sql = "SELECT * FROM portfolio_accounts"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        rows = self.conn.execute(sql + " ORDER BY created_at DESC, id DESC").fetchall()
        return [self._account(row) for row in rows]

    def set_strategy(self, account_id: int, task_id: str, bound_at: str) -> Account:
        now = datetime.now().isoformat()
        self.conn.execute(
            "UPDATE portfolio_accounts SET strategy_task_id = ?, strategy_bound_at = ?, strategy_unbound_at = NULL, updated_at = ? WHERE id = ?",
            (task_id, bound_at, now, account_id),
        )
        return cast(Account, self.get_account(account_id))

    def clear_strategy(self, account_id: int, unbound_at: str) -> Account:
        now = datetime.now().isoformat()
        self.conn.execute(
            "UPDATE portfolio_accounts SET strategy_task_id = NULL, strategy_unbound_at = ?, updated_at = ? WHERE id = ?",
            (unbound_at, now, account_id),
        )
        return cast(Account, self.get_account(account_id))

    def add_trade(self, account_id: int, symbol: str, direction: str, price: float, shares: int, trade_date: str):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO portfolio_account_trades (account_id, symbol, direction, price, shares, trade_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account_id, symbol, direction, price, shares, trade_date, now),
        )
        self.conn.commit()

    def list_trades(self, account_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM portfolio_account_trades WHERE account_id = ? ORDER BY trade_date, id", (account_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def current_holdings(self, account_id: int) -> dict[str, int]:
        holdings: dict[str, int] = {}
        for trade in self.list_trades(account_id):
            delta = trade["shares"] if trade["direction"] == "buy" else -trade["shares"]
            holdings[trade["symbol"]] = holdings.get(trade["symbol"], 0) + delta
        return {symbol: shares for symbol, shares in holdings.items() if shares > 0}

    def archive_strategy_state(self, account_id: int, archived_at: str):
        self.conn.execute(
            "UPDATE portfolio_strategy_targets SET archived_at = COALESCE(archived_at, ?) WHERE account_id = ?",
            (archived_at, account_id),
        )
        self.conn.execute(
            "UPDATE portfolio_strategy_target_history SET archived_at = COALESCE(archived_at, ?) WHERE account_id = ?",
            (archived_at, account_id),
        )
        self.conn.execute(
            "UPDATE portfolio_strategy_alerts SET archived_at = COALESCE(archived_at, ?) WHERE account_id = ?",
            (archived_at, account_id),
        )
