from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from services.portfolio.db import get_connection
from services.portfolio.holdings_service import get_holdings
from services.portfolio.repository import AccountRepository
from services.portfolio.strategy_targets import get_current_targets


class BuyOpportunitySink(Protocol):
    def emit(self, alert: "BuyOpportunityAlert") -> None: ...


@dataclass(frozen=True)
class BuyOpportunityAlert:
    account_id: int
    task_id: str
    symbol: str
    reference_price: float
    previous_close: float
    target_quantity: int
    actual_shares: int
    remaining_quantity: int
    signal_date: str
    valuation_date: str


def evaluate_buy_opportunities(as_of_date: str, sink: BuyOpportunitySink, *, connection: sqlite3.Connection | None = None, store=None) -> int:
    date.fromisoformat(as_of_date)
    if store is None:
        from services.market_data.duckdb_store import get_store
        store = get_store()
    owns = connection is None
    conn = connection or get_connection()
    try:
        repo = AccountRepository(conn)
        emitted = 0
        for account in (a for a in repo.list_accounts() if a.strategy_task_id):
            targets = [t for t in get_current_targets(account.id, as_of_date, conn) if t.target_quantity > 0]
            closes = store.query_previous_close(tuple(t.symbol for t in targets), as_of_date)
            actual = {h.symbol: h.actual_shares for h in get_holdings(account.id, as_of_date, conn)}
            for target in targets:
                close = closes.get(target.symbol)
                if close is None:
                    continue
                actual_shares = actual.get(target.symbol, 0)
                remaining = max(target.target_quantity - actual_shares, 0)
                revision = f"{account.strategy_task_id}:{target.effective_date}"
                current = repo.current_alert(account.id, target.symbol)
                payload = json.loads(current["payload"] or "{}") if current else {}
                state = current["state"] if current and payload.get("revision") == revision else "armed"
                if close >= target.reference_price:
                    state = "armed"
                elif remaining > 0 and state == "armed":
                    sink.emit(BuyOpportunityAlert(account.id, account.strategy_task_id or "", target.symbol, target.reference_price, float(close), target.target_quantity, actual_shares, remaining, as_of_date, as_of_date))
                    emitted += 1
                    state = "triggered"
                repo.save_alert(account.id, target.symbol, state, json.dumps({"revision": revision}), datetime.now().isoformat())
        conn.commit()
        return emitted
    finally:
        if owns:
            conn.close()
