"""Portfolio-owned strategy target history.

The backtest result is an immutable source document. This module parses its
explicit target recommendation section once at binding time and then serves
only the account-owned SQLite materialization.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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


def _task_connection() -> sqlite3.Connection:
    return get_connection()


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
            effective_date = str(raw_revision.get("effective_date", raw_revision.get("date")))
            datetime.strptime(effective_date, "%Y-%m-%d")
            raw_targets = raw_revision["targets"]
            if not isinstance(raw_targets, list):
                raise TypeError
            targets = tuple(
                StrategyTarget(
                    symbol=str(item["symbol"]),
                    target_quantity=int(item.get("target_quantity", item.get("quantity", item.get("shares")))),
                    reference_price=float(item.get("reference_price", item.get("price"))),
                    status=str(item.get("status", "active")),
                    effective_date=effective_date,
                    source_task_id=task_id,
                )
                for item in raw_targets
            )
            revisions.append(StrategyTargetRevision(effective_date, targets, task_id))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise TargetRecommendationUnavailable("backtest target recommendations are invalid") from exc
    return sorted(revisions, key=lambda revision: revision.effective_date)


def _load_task_result(task_id: str, connection: sqlite3.Connection) -> dict:
    row = connection.execute(
        "SELECT result FROM backtest_tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    if row is None or not row["result"]:
        raise TargetRecommendationUnavailable("backtest task result is unavailable")
    try:
        result = json.loads(row["result"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise TargetRecommendationUnavailable("backtest task result is invalid") from exc
    return result


def materialize_targets(
    account_id: int, task_id: str, connection: sqlite3.Connection | None = None
) -> int:
    owns_connection = connection is None
    conn = connection or _task_connection()
    try:
        repository = AccountRepository(conn)
        revisions = _result_revisions(_load_task_result(task_id, conn), task_id)
        now = datetime.now().isoformat()
        for revision in revisions:
            repository.archive_target_history(account_id, revision.effective_date, now)
            repository.add_target_history(
                account_id,
                revision.effective_date,
                json.dumps(
                    {"task_id": task_id, "targets": [target.__dict__ for target in revision.targets]},
                    ensure_ascii=False,
                ),
                now,
            )

        repository.replace_current_targets(
            account_id,
            [
                (target.symbol, target.target_quantity, target.reference_price, target.status, target.effective_date)
                for target in revisions[-1].targets
            ],
            now,
        )
        if owns_connection:
            conn.commit()
        return len(revisions[-1].targets)
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
    conn = connection or _task_connection()
    try:
        return _history_rows(account_id, conn)
    finally:
        if owns_connection:
            conn.close()


def get_current_targets(
    account_id: int, as_of_date: str, connection: sqlite3.Connection | None = None
) -> list[StrategyTarget]:
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
    return any(
        target.symbol == symbol and target.target_quantity > 0
        for target in get_current_targets(account_id, as_of_date, connection)
    )
