from __future__ import annotations

import sqlite3
import logging
from datetime import date

from services.portfolio.db import get_connection
from services.portfolio.models import Holding, Trade
from services.portfolio.repository import AccountRepository
from services.portfolio.strategy_targets import get_current_targets, is_buy_allowed


logger = logging.getLogger(__name__)


def _normalize_market(market: str) -> str:
    normalized = market.upper()
    if normalized in {"A", "CN"}:
        return "A"
    if normalized == "HK":
        return "HK"
    if normalized == "US":
        return "US"
    raise ValueError(f"unsupported market: {market}")


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


def delete_trade(account_id: int, trade_id: int, connection: sqlite3.Connection | None = None) -> None:
    """删除交易后完整重放账户流水，拒绝跨账户和会产生负持仓的删除。"""
    owns = connection is None
    conn = connection or get_connection()
    started = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            started = True
        repo = AccountRepository(conn)
        trade = repo.get_trade(trade_id)
        if trade is None or trade["account_id"] != account_id:
            raise ValueError("trade does not belong to account")
        shares_by_symbol: dict[str, int] = {}
        costs_by_symbol: dict[str, float] = {}
        projected_realized: list[tuple[float, int]] = []
        for row in repo.list_trades(account_id):
            if row["id"] == trade_id:
                continue
            symbol = row["symbol"]
            shares = shares_by_symbol.get(symbol, 0)
            cost = costs_by_symbol.get(symbol, 0.0)
            if row["direction"] == "buy":
                shares += row["shares"]
                cost += row["shares"] * row["price"] + row["fee"]
                realized = 0.0
            else:
                if row["shares"] > shares:
                    raise ValueError("deleting trade would create negative holdings")
                average = cost / shares if shares else 0.0
                shares -= row["shares"]
                cost -= average * row["shares"]
                realized = row["price"] * row["shares"] - average * row["shares"] - row["fee"] - row["tax"]
            projected_realized.append((realized, row["id"]))
            shares_by_symbol[symbol] = shares
            costs_by_symbol[symbol] = cost
        conn.execute("DELETE FROM portfolio_account_trades WHERE id = ? AND account_id = ?", (trade_id, account_id))
        for realized, row_id in projected_realized:
            conn.execute("UPDATE portfolio_account_trades SET realized_pnl = ? WHERE id = ?", (realized, row_id))
        if started:
            conn.commit()
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
            alert = repo.current_alert(account_id, symbol) if target else None
            result.append(Holding(account_id, symbol, actual, cost / actual if actual else 0.0, realized.get(symbol, 0.0), target_quantity, target.reference_price if target else None, target.status if target else None, max(target_quantity - actual, 0), alert["state"] if alert else None))
        return result
    finally:
        if owns:
            conn.close()


def take_all_snapshots(
    market_quotes: dict[str, tuple[str, dict[str, float]]],
    *,
    connection: sqlite3.Connection | None = None,
) -> None:
    """Persist market-specific valuation snapshots without inventing prices."""
    owns = connection is None
    conn = connection or get_connection()
    try:
        repo = AccountRepository(conn)
        rows = []
        for account in repo.list_accounts():
            market = _normalize_market(account.market)
            quote = market_quotes.get(market)
            if quote is None:
                logger.warning("snapshot skipped: no market quotes for account=%s market=%s", account.id, account.market)
                continue
            snapshot_date, current_prices = quote
            date.fromisoformat(snapshot_date)
            holdings = get_holdings(account.id, snapshot_date, conn)
            market_value = sum(
                holding.actual_shares * price
                for holding in holdings
                if (price := _resolve_price(market, holding.symbol, current_prices)) is not None
            )
            for holding in holdings:
                if _resolve_price(market, holding.symbol, current_prices) is None:
                    logger.warning("snapshot quote unavailable: account=%s market=%s symbol=%s", account.id, account.market, holding.symbol)
            rows.append((account.id, snapshot_date, market_value, 0.0, market_value))
        conn.executemany(
            "INSERT OR REPLACE INTO portfolio_account_snapshots "
            "(account_id, date, total_value, cash, market_value) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        if owns:
            conn.close()


def _symbol_candidates(market: str, symbol: str) -> tuple[str, ...]:
    normalized = _normalize_market(market)
    if "." in symbol:
        return (symbol,)
    if normalized == "A":
        return (f"{symbol}.SH", f"{symbol}.SZ", symbol)
    if normalized == "HK":
        return (f"{symbol}.HK", symbol)
    return (f"{symbol}.US", symbol)


def _resolve_price(market: str, symbol: str, quotes: dict[str, float]) -> float | None:
    for candidate in _symbol_candidates(market, symbol):
        if candidate in quotes:
            return float(quotes[candidate])
    return None


def _resolve_quote(market: str, symbol: str, quotes: dict[str, tuple[float, str]]) -> tuple[float, str] | None:
    for candidate in _symbol_candidates(market, symbol):
        if candidate in quotes:
            price, quote_date = quotes[candidate]
            return float(price), quote_date
    return None


def build_snapshot(
    *,
    as_of_date: str,
    account_id: int | None,
    cost_method: str,
    store,
    connection: sqlite3.Connection,
) -> dict:
    """Build the v1 snapshot contract with explicit missing-price state."""
    if cost_method not in {"fifo", "avg"}:
        raise ValueError("unsupported cost method")
    date.fromisoformat(as_of_date)
    repo = AccountRepository(connection)
    accounts = repo.list_accounts()
    if account_id is not None:
        accounts = [account for account in accounts if account.id == account_id]
        if not accounts:
            raise ValueError("account not found")

    account_items = []
    total_market_value = 0.0
    realized_pnl = 0.0
    unrealized_pnl = 0.0
    fee_total = 0.0
    tax_total = 0.0
    for account in accounts:
        holdings = get_holdings(account.id, as_of_date, connection)
        quotes = store.query_latest_closes(
            _normalize_market(account.market),
            tuple(holding.symbol for holding in holdings),
            as_of_date,
        )
        positions = []
        account_market_value = 0.0
        account_unrealized = 0.0
        for holding in holdings:
            quote = _resolve_quote(account.market, holding.symbol, quotes)
            available = quote is not None
            last_price = quote[0] if quote else None
            quote_date = quote[1] if quote else None
            market_value = holding.actual_shares * last_price if last_price is not None else 0.0
            pnl = market_value - holding.actual_shares * holding.average_cost if available else None
            pnl_pct = (pnl / (holding.actual_shares * holding.average_cost) * 100) if pnl is not None and holding.average_cost else None
            if pnl is not None:
                account_unrealized += pnl
            account_market_value += market_value
            positions.append({
                "symbol": holding.symbol,
                "market": "cn" if _normalize_market(account.market) == "A" else _normalize_market(account.market).lower(),
                "currency": account.base_currency,
                "quantity": holding.actual_shares,
                "avg_cost": holding.average_cost,
                "total_cost": holding.actual_shares * holding.average_cost,
                "last_price": last_price,
                "market_value_base": market_value,
                "unrealized_pnl_base": pnl,
                "unrealized_pnl_pct": pnl_pct,
                "valuation_currency": account.base_currency,
                "price_source": "history_close" if available else "missing",
                "price_provider": "DuckDBStore" if available else None,
                "price_date": quote_date,
                "price_stale": bool(quote_date and quote_date < as_of_date),
                "price_available": available,
                "target_quantity": holding.target_quantity,
                "reference_price": holding.reference_price,
                "remaining_quantity": holding.remaining_quantity,
                "over_target_quantity": max(holding.actual_shares - holding.target_quantity, 0),
                "target_status": holding.target_status,
                "alert_status": holding.alert_status,
            })
        account_items.append({
            "account_id": account.id,
            "account_name": account.name,
            "broker": None,
            "market": "cn" if _normalize_market(account.market) == "A" else _normalize_market(account.market).lower(),
            "base_currency": account.base_currency,
            "as_of": as_of_date,
            "cost_method": cost_method,
            "total_cash": 0.0,
            "total_market_value": account_market_value,
            "total_equity": account_market_value,
            "realized_pnl": sum(item.realized_pnl for item in holdings),
            "unrealized_pnl": account_unrealized,
            "fee_total": 0.0,
            "tax_total": 0.0,
            "fx_stale": False,
            "positions": positions,
        })
        total_market_value += account_market_value
        realized_pnl += account_items[-1]["realized_pnl"]
        unrealized_pnl += account_unrealized
    currencies = {account.base_currency for account in accounts}
    return {
        "as_of": as_of_date,
        "cost_method": cost_method,
        "currency": next(iter(currencies)) if len(currencies) == 1 else "MIXED",
        "account_count": len(accounts),
        "total_cash": 0.0,
        "total_market_value": total_market_value,
        "total_equity": total_market_value,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "fee_total": fee_total,
        "tax_total": tax_total,
        "fx_stale": False,
        "accounts": account_items,
    }
