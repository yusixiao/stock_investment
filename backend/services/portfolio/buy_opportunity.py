from __future__ import annotations

import json
import hashlib
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


def evaluate_buy_opportunities(as_of_date: str, sink: BuyOpportunitySink, *, connection: sqlite3.Connection | None = None, store=None, markets: set[str] | None = None) -> int:
    date.fromisoformat(as_of_date)
    if store is None:
        from services.market_data.duckdb_store import get_store
        store = get_store()
    owns = connection is None
    conn = connection or get_connection()
    started = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            started = True
        repo = AccountRepository(conn)
        emitted = 0
        for account in (a for a in repo.list_accounts() if a.strategy_task_id):
            if not isinstance(account.market, str):
                raise ValueError(f"unsupported market: {account.market}")
            market = account.market.upper()
            if market not in {"A", "HK", "US"}:
                raise ValueError(f"unsupported market: {account.market}")
            if markets is not None and market not in markets:
                continue
            valuation_date = store.previous_trading_date(market, as_of_date)
            if valuation_date is None:
                continue
            targets = [t for t in get_current_targets(account.id, valuation_date, conn) if t.target_quantity > 0]
            closes = store.query_previous_close(market, tuple(t.symbol for t in targets), valuation_date)
            actual = {h.symbol: h.actual_shares for h in get_holdings(account.id, valuation_date, conn)}
            for target in targets:
                close = closes.get(target.symbol)
                if close is None:
                    continue
                actual_shares = actual.get(target.symbol, 0)
                remaining = max(target.target_quantity - actual_shares, 0)
                revision_source = json.dumps({
                    "task_id": account.strategy_task_id,
                    "effective_date": target.effective_date,
                    "symbol": target.symbol,
                    "target_quantity": target.target_quantity,
                    "reference_price": target.reference_price,
                    "status": target.status,
                }, sort_keys=True, separators=(",", ":"))
                revision = hashlib.sha256(revision_source.encode()).hexdigest()
                current = repo.current_alert(account.id, target.symbol)
                payload = json.loads(current["payload"] or "{}") if current else {}
                state = current["state"] if current and payload.get("revision") == revision else "armed"
                alert = None
                if close >= target.reference_price:
                    state = "armed"
                elif remaining > 0 and state == "armed":
                    trigger_payload = json.dumps({"revision": revision, "valuation_date": valuation_date, "processed": True})
                    if repo.claim_alert(account.id, target.symbol, revision, valuation_date, trigger_payload, datetime.now().isoformat()):
                        alert = BuyOpportunityAlert(account.id, account.strategy_task_id or "", target.symbol, target.reference_price, float(close), target.target_quantity, actual_shares, remaining, valuation_date, valuation_date)
                    state = "triggered"
                if alert is None or state != "triggered":
                    repo.save_alert(account.id, target.symbol, state, json.dumps({"revision": revision, "valuation_date": valuation_date, "processed": state == "triggered"}), datetime.now().isoformat())
                if alert is not None:
                    sink.emit(alert)
                    emitted += 1
        if started:
            conn.commit()
        return emitted
    except Exception:
        if started:
            conn.rollback()
        raise
    finally:
        if owns:
            conn.close()
