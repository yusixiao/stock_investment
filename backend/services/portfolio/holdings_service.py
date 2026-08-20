from __future__ import annotations

import sqlite3
from datetime import date

from services.portfolio.db import get_connection
from services.portfolio.models import Holding, Trade
from services.portfolio.repository import AccountRepository
from services.portfolio.strategy_targets import get_current_targets, is_buy_allowed


def record_trade(account_id: int, symbol: str, side: str, quantity: int, price: float, trade_date: str, fee: float = 0, tax: float = 0, connection: sqlite3.Connection | None = None) -> Trade:
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if quantity <= 0 or price <= 0:
        raise ValueError("quantity and price must be positive")
    if fee < 0 or tax < 0:
        raise ValueError("fee and tax must be non-negative")
    date.fromisoformat(trade_date)
    owns = connection is None
    conn = connection or get_connection()
    started = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            started = True
        repo = AccountRepository(conn)
        account = repo.get_account(account_id)
        if account is None:
            raise ValueError("account not found")
        if side == "buy" and account.strategy_task_id and not is_buy_allowed(account_id, symbol, trade_date, conn):
            raise ValueError("buy symbol is not a current strategy target")
        holdings = _project(repo.list_trades(account_id), trade_date)
        if side == "sell" and quantity > holdings.get(symbol, (0, 0.0))[0]:
            raise ValueError("sell quantity exceeds holding")
        realized = 0.0
        if side == "sell":
            shares, cost = holdings.get(symbol, (0, 0.0))
            realized = price * quantity - (cost / shares if shares else 0.0) * quantity - fee - tax
        repo.add_trade(account_id, symbol, side, price, quantity, trade_date, fee, tax, realized)
        row = conn.execute("SELECT * FROM portfolio_account_trades WHERE rowid = last_insert_rowid()").fetchone()
        if started:
            conn.commit()
        return Trade(row["id"], account_id, symbol, side, quantity, price, trade_date, fee, tax, realized)
    except Exception:
        if started:
            conn.rollback()
        raise
    finally:
        if owns:
            conn.close()


def _project(trades: list[dict], as_of_date: str) -> dict[str, tuple[int, float]]:
    state: dict[str, tuple[int, float]] = {}
    for trade in trades:
        if trade["trade_date"] > as_of_date:
            continue
        shares, cost = state.get(trade["symbol"], (0, 0.0))
        if trade["direction"] == "buy":
            shares += trade["shares"]
            cost += trade["shares"] * trade["price"] + trade["fee"]
        else:
            average = cost / shares if shares else 0.0
            shares -= trade["shares"]
            cost -= average * trade["shares"]
        state[trade["symbol"]] = (shares, cost)
    return state


def get_holdings(account_id: int, as_of_date: str | None = None, connection: sqlite3.Connection | None = None) -> list[Holding]:
    as_of = as_of_date or date.today().isoformat()
    date.fromisoformat(as_of)
    owns = connection is None
    conn = connection or get_connection()
    try:
        repo = AccountRepository(conn)
        trades = [trade for trade in repo.list_trades(account_id) if trade["trade_date"] <= as_of]
        state = _project(trades, as_of)
        realized: dict[str, float] = {}
        for trade in trades:
            if trade["direction"] == "sell":
                realized[trade["symbol"]] = realized.get(trade["symbol"], 0.0) + trade["realized_pnl"]
        targets = {target.symbol: target for target in get_current_targets(account_id, as_of, conn)}
        result = []
        for symbol in sorted(set(state) | set(targets)):
            shares, cost = state.get(symbol, (0, 0.0))
            target = targets.get(symbol)
            if shares <= 0 and (target is None or target.target_quantity <= 0):
                continue
            actual = max(shares, 0)
            target_quantity = target.target_quantity if target else 0
            result.append(Holding(account_id, symbol, actual, cost / actual if actual else 0.0, realized.get(symbol, 0.0), target_quantity, target.reference_price if target else None, target.status if target else None, max(target_quantity - actual, 0)))
        return result
    finally:
        if owns:
            conn.close()
