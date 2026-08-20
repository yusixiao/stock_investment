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

    def add_trade(self, account_id: int, symbol: str, direction: str, price: float, shares: int, trade_date: str, fee: float = 0, tax: float = 0, realized_pnl: float = 0):
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO portfolio_account_trades (account_id, symbol, direction, price, shares, fee, tax, realized_pnl, trade_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, symbol, direction, price, shares, fee, tax, realized_pnl, trade_date, now),
        )

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

    def current_alert(self, account_id: int, symbol: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM portfolio_strategy_alerts WHERE account_id = ? AND symbol = ? AND archived_at IS NULL", (account_id, symbol)).fetchone()

    def save_alert(self, account_id: int, symbol: str, state: str, payload: str, updated_at: str) -> None:
        started = not self.conn.in_transaction
        try:
            if started:
                self.conn.execute("BEGIN IMMEDIATE")
            current = self.current_alert(account_id, symbol)
            if current:
                self.conn.execute("UPDATE portfolio_strategy_alerts SET state = ?, payload = ?, updated_at = ? WHERE id = ? AND archived_at IS NULL", (state, payload, updated_at, current["id"]))
            else:
                self.conn.execute("INSERT INTO portfolio_strategy_alerts (account_id, symbol, state, payload, updated_at) VALUES (?, ?, ?, ?, ?)", (account_id, symbol, state, payload, updated_at))
            if started:
                self.conn.commit()
        except Exception:
            if started:
                self.conn.rollback()
            raise

    def claim_alert(self, account_id: int, symbol: str, revision: str, valuation_date: str, payload: str, updated_at: str) -> bool:
        """Atomically claim a new trigger; only armed/new revisions can win."""
        started = not self.conn.in_transaction
        try:
            if started:
                self.conn.execute("BEGIN IMMEDIATE")
            current = self.current_alert(account_id, symbol)
            if current is None:
                self.conn.execute(
                    "INSERT INTO portfolio_strategy_alerts (account_id, symbol, state, payload, updated_at) VALUES (?, ?, 'triggered', ?, ?)",
                    (account_id, symbol, payload, updated_at),
                )
                if started:
                    self.conn.commit()
                return True
            cursor = self.conn.execute(
                """
                UPDATE portfolio_strategy_alerts
                SET state = 'triggered', payload = ?, updated_at = ?
                WHERE id = ? AND archived_at IS NULL
                  AND (
                      json_extract(COALESCE(payload, '{}'), '$.revision') IS NULL
                      OR json_extract(COALESCE(payload, '{}'), '$.revision') <> ?
                      OR (
                          state = 'armed'
                          AND COALESCE(json_extract(COALESCE(payload, '{}'), '$.valuation_date'), '') <> ?
                      )
                  )
                """,
                (payload, updated_at, current["id"], revision, valuation_date),
            )
            claimed = cursor.rowcount == 1
            if started:
                self.conn.commit()
            return claimed
        except sqlite3.IntegrityError:
            if started:
                self.conn.rollback()
            return False
        except Exception:
            if started:
                self.conn.rollback()
            raise

    def strategy_target_history(self, account_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT effective_date, targets FROM portfolio_strategy_target_history "
            "WHERE account_id = ? AND archived_at IS NULL ORDER BY effective_date, id",
            (account_id,),
        ).fetchall()

    def archive_target_history(self, account_id: int, effective_date: str, archived_at: str) -> None:
        self.conn.execute(
            "UPDATE portfolio_strategy_target_history SET archived_at = COALESCE(archived_at, ?) "
            "WHERE account_id = ? AND effective_date = ? AND archived_at IS NULL",
            (archived_at, account_id, effective_date),
        )

    def add_target_history(self, account_id: int, effective_date: str, payload: str, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO portfolio_strategy_target_history "
            "(account_id, effective_date, targets, created_at) VALUES (?, ?, ?, ?)",
            (account_id, effective_date, payload, created_at),
        )

    def replace_current_targets(self, account_id: int, targets: list[tuple], archived_at: str) -> None:
        self.conn.execute(
            "UPDATE portfolio_strategy_targets SET archived_at = COALESCE(archived_at, ?) WHERE account_id = ?",
            (archived_at, account_id),
        )
        self.conn.executemany(
            "INSERT INTO portfolio_strategy_targets "
            "(account_id, symbol, target_quantity, reference_price, status, effective_date, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(account_id, *target, archived_at) for target in targets],
        )

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
