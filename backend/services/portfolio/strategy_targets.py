"""Portfolio-owned strategy target history.

The backtest result is an immutable source document. The production contract
is its ``raw_trades`` list, processed by ``(date, original index)``: a buy
establishes or replaces a symbol target with its latest quantity/price, while
any sell, including a partial sell, zeroes that symbol and preserves its prior
reference price. Every revision inherits other symbols. Explicit target
history remains supported for older producers; malformed or target-less
results fail closed. Reads after binding use only the account-owned SQLite
materialization.
"""

from __future__ import annotations

import json
import sqlite3
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from services.backtest.task_manager import task_manager
from services.portfolio.db import get_connection
from services.portfolio.repository import AccountRepository


class TargetRecommendationUnavailable(ValueError):
    """The selected backtest result does not contain a safe target contract."""


@dataclass(frozen=True)
class StrategyTarget:
    symbol: str
    target_quantity: int
    reference_price: float
    status: str
    effective_date: str
    source_task_id: str | None = None


@dataclass(frozen=True)
class StrategyTargetRevision:
    effective_date: str
    targets: tuple[StrategyTarget, ...]
    source_task_id: str | None = None


def _iso_date(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 10:
        raise TargetRecommendationUnavailable("target date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise TargetRecommendationUnavailable("target date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise TargetRecommendationUnavailable("target date must be YYYY-MM-DD")
    return value


def _quantity(value: Any, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        requirement = "non-negative" if allow_zero else "positive"
        raise TargetRecommendationUnavailable(f"target quantity must be a {requirement} integer")
    return value


def _positive_price(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TargetRecommendationUnavailable("reference price must be finite and positive")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise TargetRecommendationUnavailable("reference price must be finite and positive")
    return result


def _target(
    symbol: Any, quantity: Any, price: Any, status: str, effective_date: str,
    task_id: str, *, allow_zero: bool = False,
) -> StrategyTarget:
    if not isinstance(symbol, str) or not symbol:
        raise TargetRecommendationUnavailable("target symbol is required")
    return StrategyTarget(
        symbol=symbol,
        target_quantity=_quantity(quantity, allow_zero=allow_zero),
        reference_price=_positive_price(price),
        status=status,
        effective_date=effective_date,
        source_task_id=task_id,
    )


def _result_revisions(result: Any, task_id: str) -> list[StrategyTargetRevision]:
    if not isinstance(result, dict):
        raise TargetRecommendationUnavailable("backtest result has no explicit target recommendations")
    raw_revisions = (
        result.get("strategy_targets")
        or result.get("target_history")
        or result.get("strategy_target_history")
        or (result.get("execution") or {}).get("strategy_targets")
    )
    if not isinstance(raw_revisions, list) or not raw_revisions:
        raise TargetRecommendationUnavailable("backtest result has no explicit target recommendations")

    revisions: list[StrategyTargetRevision] = []
    try:
        for raw_revision in raw_revisions:
            effective_date = _iso_date(raw_revision.get("effective_date", raw_revision.get("date")))
            raw_targets = raw_revision["targets"]
            if not isinstance(raw_targets, list):
                raise TypeError
            targets = tuple(
                _target(
                    item.get("symbol"),
                    item.get("target_quantity", item.get("quantity", item.get("shares"))),
                    item.get("reference_price", item.get("price")),
                    str(item.get("status", "active")), effective_date, task_id, allow_zero=True,
                )
                for item in raw_targets
            )
            revisions.append(StrategyTargetRevision(effective_date, targets, task_id))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise TargetRecommendationUnavailable("backtest target recommendations are invalid") from exc
    return sorted(revisions, key=lambda revision: revision.effective_date)


def _load_task_result(task_id: str, connection: sqlite3.Connection | None = None) -> dict:
    task = task_manager.get_result(task_id, connection=connection)
    if not task or not task.get("result"):
        raise TargetRecommendationUnavailable("backtest task result is unavailable")
    return task["result"]


def _raw_trade_revisions(result: dict, task_id: str) -> list[StrategyTargetRevision]:
    raw_trades = result.get("raw_trades")
    if not isinstance(raw_trades, list) or not raw_trades:
        raise TargetRecommendationUnavailable("backtest result has no target recommendations")
    state: dict[str, StrategyTarget] = {}
    revisions: list[StrategyTargetRevision] = []
    try:
        # Same-day ties use raw result order; partial sells mean strategy exit,
        # not an account-trade quantity adjustment.
        ordered = sorted(enumerate(raw_trades), key=lambda pair: (_iso_date(pair[1]["date"]), pair[0]))
        for _, trade in ordered:
            effective_date = _iso_date(trade["date"])
            symbol = trade["symbol"]
            direction = trade["direction"]
            quantity = _quantity(trade["shares"])
            price = _positive_price(trade["price"])
            if not isinstance(symbol, str) or not symbol or direction not in {"buy", "sell"}:
                raise TargetRecommendationUnavailable("raw trade target recommendation is invalid")
            previous = state.get(symbol)
            if direction == "buy":
                state[symbol] = _target(symbol, quantity, price, "active", effective_date, task_id)
            else:
                reference_price = previous.reference_price if previous else price
                state[symbol] = StrategyTarget(
                    symbol=symbol, target_quantity=0, reference_price=reference_price,
                    status="exited", effective_date=effective_date, source_task_id=task_id,
                )
            revisions.append(StrategyTargetRevision(effective_date, tuple(state.values()), task_id))
    except (KeyError, TypeError, TargetRecommendationUnavailable) as exc:
        if isinstance(exc, TargetRecommendationUnavailable):
            raise
        raise TargetRecommendationUnavailable("raw trade target recommendation is invalid") from exc
    return revisions


def materialize_targets(
    account_id: int, task_id: str, connection: sqlite3.Connection | None = None
) -> int:
    owns_connection = connection is None
    conn = connection or get_connection()
    try:
        repository = AccountRepository(conn)
        result = _load_task_result(task_id, connection=conn)
        revisions = _result_revisions(result, task_id) if (
            result.get("strategy_targets") or result.get("target_history")
            or result.get("strategy_target_history") or (result.get("execution") or {}).get("strategy_targets")
        ) else _raw_trade_revisions(result, task_id)
        now = datetime.now().isoformat()
        archived_dates: set[str] = set()
        for revision in revisions:
            if revision.effective_date not in archived_dates:
                repository.archive_target_history(account_id, revision.effective_date, now)
                archived_dates.add(revision.effective_date)
            repository.add_target_history(
                account_id,
                revision.effective_date,
                json.dumps(
                    {"task_id": task_id, "targets": [target.__dict__ for target in revision.targets]},
                    ensure_ascii=False,
                ),
                now,
            )

        as_of_date = date.today().isoformat()
        eligible = [revision for revision in revisions if revision.effective_date <= as_of_date]
        current_targets = eligible[-1].targets if eligible else ()
        repository.replace_current_targets(
            account_id,
            [
                (target.symbol, target.target_quantity, target.reference_price, target.status, target.effective_date)
                for target in current_targets
            ],
            now,
        )
        if owns_connection:
            conn.commit()
        return len(current_targets)
    except Exception:
        if owns_connection:
            conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def _history_rows(account_id: int, connection: sqlite3.Connection) -> list[StrategyTargetRevision]:
    rows = AccountRepository(connection).strategy_target_history(account_id)
    revisions = []
    for row in rows:
        payload = json.loads(row["targets"])
        task_id = payload.get("task_id")
        targets = tuple(
            StrategyTarget(
                symbol=item["symbol"], target_quantity=int(item["target_quantity"]),
                reference_price=float(item["reference_price"]), status=item["status"],
                effective_date=row["effective_date"], source_task_id=task_id,
            ) for item in payload["targets"]
        )
        revisions.append(StrategyTargetRevision(row["effective_date"], targets, task_id))
    return revisions


def get_target_history(
    account_id: int, connection: sqlite3.Connection | None = None
) -> list[StrategyTargetRevision]:
    owns_connection = connection is None
    conn = connection or get_connection()
    try:
        return _history_rows(account_id, conn)
    finally:
        if owns_connection:
            conn.close()


def get_current_targets(
    account_id: int, as_of_date: str, connection: sqlite3.Connection | None = None
) -> list[StrategyTarget]:
    as_of_date = _iso_date(as_of_date)
    revisions = [r for r in get_target_history(account_id, connection) if r.effective_date <= as_of_date]
    if not revisions:
        return []
    latest: dict[str, StrategyTarget] = {}
    for revision in revisions:
        for target in revision.targets:
            latest[target.symbol] = target
    return list(latest.values())


def is_buy_allowed(
    account_id: int, symbol: str, as_of_date: str, connection: sqlite3.Connection | None = None
) -> bool:
    _iso_date(as_of_date)
    return any(
        target.symbol == symbol and target.target_quantity > 0
        for target in get_current_targets(account_id, as_of_date, connection)
    )
