"""市场数据 refresh 生命周期的 SQLite 状态存储。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import PORTFOLIO_DB
from services.db_schema import init_market_refresh_tables


class RefreshAlreadyRunning(RuntimeError):
    """已有 refresh 在运行，新的 refresh 不排队。"""

    def __init__(self, refresh_id: str):
        self.refresh_id = refresh_id
        super().__init__(f"Market refresh already running: {refresh_id}")


@dataclass
class RefreshRecord:
    refresh_id: str
    source: str
    status: str
    created_at: str
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    market_states: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RefreshStateStore:
    """以独立 SQLite 记录 refresh 状态，避免复用回测任务表。"""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or PORTFOLIO_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            init_market_refresh_tables(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> RefreshRecord:
        return RefreshRecord(
            refresh_id=row["refresh_id"],
            source=row["source"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
            market_states=json.loads(row["market_states"] or "{}"),
        )

    def start_refresh(self, source: str) -> RefreshRecord:
        now = _now()
        refresh_id = f"refresh-{now.replace(':', '').replace('+00:00', '')}-{uuid.uuid4().hex[:8]}"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT refresh_id FROM market_refreshes WHERE status = 'running' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if active:
                raise RefreshAlreadyRunning(active["refresh_id"])
            conn.execute(
                """
                INSERT INTO market_refreshes
                    (refresh_id, source, status, created_at, started_at, market_states)
                VALUES (?, ?, 'running', ?, ?, '{}')
                """,
                (refresh_id, source, now, now),
            )
        return self.get(refresh_id)

    def get(self, refresh_id: str) -> RefreshRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_refreshes WHERE refresh_id = ?", (refresh_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown refresh_id: {refresh_id}")
        return self._record_from_row(row)

    def get_active(self) -> RefreshRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM market_refreshes WHERE status = 'running' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return self._record_from_row(row) if row else None

    def record_market_stage(
        self,
        refresh_id: str,
        market: str,
        stage: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT market_states FROM market_refreshes WHERE refresh_id = ?",
                (refresh_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown refresh_id: {refresh_id}")
            states = json.loads(row["market_states"] or "{}")
            states.setdefault(market, {})[stage] = {
                "status": status,
                "updated_at": _now(),
                "detail": detail or {},
            }
            conn.execute(
                "UPDATE market_refreshes SET market_states = ? WHERE refresh_id = ?",
                (json.dumps(states, ensure_ascii=False), refresh_id),
            )

    def finish_market(
        self,
        refresh_id: str,
        market: str,
        market_version: int | None,
        cache_status: str,
        stale: bool,
    ) -> None:
        self.record_market_stage(
            refresh_id,
            market,
            "result",
            "ready" if cache_status == "ready" else cache_status,
            {
                "market_version": market_version,
                "cache_status": cache_status,
                "stale": stale,
            },
        )

    def get_market_version(self, market: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT version FROM market_refresh_versions WHERE market = ?",
                (market,),
            ).fetchone()
        return int(row["version"]) if row else 0

    def advance_market_version(self, market: str) -> int:
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT version FROM market_refresh_versions WHERE market = ?",
                (market,),
            ).fetchone()
            version = (int(row["version"]) if row else 0) + 1
            conn.execute(
                """
                INSERT INTO market_refresh_versions(market, version, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(market) DO UPDATE SET
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (market, version, now),
            )
        return version

    def finish_refresh(
        self, refresh_id: str, status: str, error: str | None = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE market_refreshes SET status = ?, finished_at = ?, error = ? "
                "WHERE refresh_id = ?",
                (status, _now(), error, refresh_id),
            )
            conn.execute(
                """
                DELETE FROM market_refreshes
                WHERE status IN ('completed', 'failed', 'interrupted')
                  AND refresh_id NOT IN (
                      SELECT refresh_id FROM market_refreshes
                      WHERE status IN ('completed', 'failed', 'interrupted')
                      ORDER BY finished_at DESC LIMIT 3
                  )
                """
            )

    def recover_interrupted(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE market_refreshes SET status = 'interrupted', finished_at = ? "
                "WHERE status = 'running'",
                (_now(),),
            )

    def get_recent(self, limit: int = 3) -> list[RefreshRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_refreshes "
                "ORDER BY COALESCE(finished_at, started_at) DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]
