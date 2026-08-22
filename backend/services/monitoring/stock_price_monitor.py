from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime

from config import PORTFOLIO_DB

from .repository import MonitoringRepository


logger = logging.getLogger(__name__)


def _close_for_symbol(market: str, symbol: str, closes: dict[str, float]) -> float | None:
    candidates = (symbol,) if "." in symbol else (
        (f"{symbol}.SH", f"{symbol}.SZ", symbol) if market == "A" else
        (f"{symbol}.HK", symbol) if market == "HK" else
        (f"{symbol}.US", symbol)
    )
    for candidate in candidates:
        if candidate in closes:
            return float(closes[candidate])
    return None


def evaluate_stock_price_monitors(
    as_of_date: str,
    markets: set[str] | None = None,
    connection: sqlite3.Connection | None = None,
    store=None,
) -> int:
    date.fromisoformat(as_of_date)
    owns_connection = connection is None
    conn = connection or _get_connection()
    if store is None:
        from services.market_data.duckdb_store import get_store

        store = get_store()

    market_filter = {market.upper() for market in markets} if markets is not None else None
    repo = MonitoringRepository(conn)
    event_count = 0
    try:
        by_market: dict[str, list] = {}
        for monitor in repo.list_stock_monitors():
            if monitor.state == "paused":
                continue
            market = monitor.market.upper()
            if market_filter is not None and market not in market_filter:
                continue
            by_market.setdefault(market, []).append(monitor)

        for market, monitors in by_market.items():
            try:
                valuation_date = store.previous_trading_date(market, as_of_date)
                if valuation_date is None:
                    continue
                symbols = tuple(monitor.symbol for monitor in monitors)
                closes = store.query_previous_close(market, symbols, valuation_date)
            except Exception as exc:  # noqa: BLE001
                logger.error("stock price monitor query failed for %s: %s", market, exc)
                continue

            for monitor in monitors:
                close = _close_for_symbol(market, monitor.symbol, closes)
                if close is None:
                    continue
                repo.update_stock_price(monitor.id, close, valuation_date)
                if close >= monitor.threshold_price:
                    if monitor.state == "triggered":
                        repo.rearm_price_monitor(monitor.id)
                elif monitor.state == "armed" and repo.claim_price_trigger(
                    monitor.id, close, valuation_date, datetime.now().isoformat()
                ):
                    event_count += 1
        return event_count
    finally:
        if owns_connection:
            conn.close()


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(PORTFOLIO_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    from services.db_schema import init_monitoring_tables

    init_monitoring_tables(conn)
    return conn
