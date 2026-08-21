import json
import sqlite3
from datetime import datetime
from typing import Any, cast

from .models import StockPriceMonitor, StrategyMonitor, StrategyRun

FREQUENCIES = {"daily", "weekly", "monthly", "quarterly"}
RUN_FINISH_STATUSES = {"success", "failed"}
STOCK_STATES = {"armed", "triggered", "paused"}


def _now() -> str:
    return datetime.now().isoformat()


def _json_load(value: str | None, default: Any) -> Any:
    return default if value is None else json.loads(value)


def _validate(value: str, allowed: set[str], field: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {field}: {value}")


class MonitoringRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _strategy(row: sqlite3.Row) -> StrategyMonitor:
        return StrategyMonitor(
            id=row["id"], name=row["name"], strategy_class=row["strategy_class"],
            filepath=row["filepath"], params=_json_load(row["params"], {}),
            market=row["market"], frequency=row["frequency"], symbols=_json_load(row["symbols"], None),
            is_active=bool(row["is_active"]), next_run_date=row["next_run_date"],
            last_run_at=row["last_run_at"], last_run_status=row["last_run_status"],
            last_error=row["last_error"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _run(row: sqlite3.Row) -> StrategyRun:
        return StrategyRun(
            id=row["id"], monitor_id=row["monitor_id"], scheduled_date=row["scheduled_date"],
            started_at=row["started_at"], finished_at=row["finished_at"], status=row["status"],
            task_id=row["task_id"], result=_json_load(row["result"], None), error=row["error"],
        )

    @staticmethod
    def _stock(row: sqlite3.Row) -> StockPriceMonitor:
        return StockPriceMonitor(
            id=row["id"], market=row["market"], symbol=row["symbol"], name=row["name"],
            threshold_price=float(row["threshold_price"]), is_active=bool(row["is_active"]),
            state=row["state"], last_price=row["last_price"], last_price_date=row["last_price_date"],
            last_triggered_at=row["last_triggered_at"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def create_strategy_monitor(self, name: str, strategy_class: str, filepath: str, params: dict,
                                market: str, frequency: str, symbols: list[str] | None = None,
                                next_run_date: str | None = None) -> StrategyMonitor:
        _validate(frequency, FREQUENCIES, "frequency")
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO monitoring_strategy_monitors (name, strategy_class, filepath, params, market, frequency, symbols, next_run_date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, strategy_class, filepath, json.dumps(params), market, frequency,
             json.dumps(symbols) if symbols is not None else None, next_run_date, now, now),
        )
        return cast(StrategyMonitor, self.get_strategy_monitor(cast(int, cur.lastrowid)))

    def get_strategy_monitor(self, monitor_id: int) -> StrategyMonitor | None:
        row = self.conn.execute("SELECT * FROM monitoring_strategy_monitors WHERE id = ?", (monitor_id,)).fetchone()
        return self._strategy(row) if row else None

    def list_strategy_monitors(self, include_inactive: bool = False) -> list[StrategyMonitor]:
        where = "" if include_inactive else " WHERE is_active = 1"
        rows = self.conn.execute("SELECT * FROM monitoring_strategy_monitors" + where + " ORDER BY created_at DESC, id DESC").fetchall()
        return [self._strategy(row) for row in rows]

    def update_strategy_monitor(self, monitor_id: int, **changes: Any) -> StrategyMonitor:
        allowed = {"name", "strategy_class", "filepath", "params", "market", "frequency", "symbols", "is_active", "next_run_date"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            monitor = self.get_strategy_monitor(monitor_id)
            if monitor is None:
                raise ValueError("strategy monitor not found")
            return monitor
        for key in ("params", "symbols"):
            if key in values and values[key] is not None:
                values[key] = json.dumps(values[key])
        if "frequency" in values:
            _validate(values["frequency"], FREQUENCIES, "frequency")
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        self.conn.execute(f"UPDATE monitoring_strategy_monitors SET {assignments} WHERE id = ?", (*values.values(), monitor_id))
        monitor = self.get_strategy_monitor(monitor_id)
        if monitor is None:
            raise ValueError("strategy monitor not found")
        return monitor

    def soft_delete_strategy_monitor(self, monitor_id: int) -> StrategyMonitor:
        return self.update_strategy_monitor(monitor_id, is_active=False)

    def create_strategy_run(self, monitor_id: int, scheduled_date: str, task_id: str | None = None) -> StrategyRun:
        started = _now()
        cur = self.conn.execute(
            "INSERT INTO monitoring_strategy_runs (monitor_id, scheduled_date, started_at, status, task_id) VALUES (?, ?, ?, 'running', ?)",
            (monitor_id, scheduled_date, started, task_id),
        )
        row = self.conn.execute("SELECT * FROM monitoring_strategy_runs WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._run(row)

    def finish_strategy_run(self, run_id: int, status: str, result: dict | None = None,
                            error: str | None = None, finished_at: str | None = None) -> StrategyRun:
        _validate(status, RUN_FINISH_STATUSES, "strategy run finish status")
        started = not self.conn.in_transaction
        try:
            if started:
                self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT * FROM monitoring_strategy_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("strategy run not found")
            if row["status"] != "running":
                raise ValueError("strategy run is already finished")
            finished = finished_at or _now()
            cursor = self.conn.execute(
                "UPDATE monitoring_strategy_runs SET status = ?, result = ?, error = ?, finished_at = ? WHERE id = ? AND status = 'running'",
                (status, json.dumps(result) if result is not None else None, error, finished, run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("strategy run is already finished")
            latest = self.conn.execute(
                "SELECT id FROM monitoring_strategy_runs WHERE monitor_id = ? ORDER BY id DESC LIMIT 1",
                (row["monitor_id"],),
            ).fetchone()
            if latest["id"] == run_id:
                self.conn.execute(
                    "UPDATE monitoring_strategy_monitors SET last_run_at = ?, last_run_status = ?, last_error = ?, updated_at = ? WHERE id = ?",
                    (finished, status, error, finished, row["monitor_id"]),
                )
            if started:
                self.conn.commit()
            return self._run(self.conn.execute("SELECT * FROM monitoring_strategy_runs WHERE id = ?", (run_id,)).fetchone())
        except Exception:
            if started:
                self.conn.rollback()
            raise

    def list_strategy_runs(self, monitor_id: int) -> list[StrategyRun]:
        rows = self.conn.execute("SELECT * FROM monitoring_strategy_runs WHERE monitor_id = ? ORDER BY scheduled_date DESC, id DESC", (monitor_id,)).fetchall()
        return [self._run(row) for row in rows]

    def create_stock_monitor(self, market: str, symbol: str, threshold_price: float, name: str | None = None) -> StockPriceMonitor:
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO monitoring_stock_monitors (market, symbol, name, threshold_price, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (market, symbol, name, threshold_price, now, now),
        )
        return cast(StockPriceMonitor, self.get_stock_monitor(cast(int, cur.lastrowid)))

    def get_stock_monitor(self, monitor_id: int) -> StockPriceMonitor | None:
        row = self.conn.execute("SELECT * FROM monitoring_stock_monitors WHERE id = ?", (monitor_id,)).fetchone()
        return self._stock(row) if row else None

    def list_stock_monitors(self, include_inactive: bool = False) -> list[StockPriceMonitor]:
        where = "" if include_inactive else " WHERE is_active = 1"
        rows = self.conn.execute("SELECT * FROM monitoring_stock_monitors" + where + " ORDER BY created_at DESC, id DESC").fetchall()
        return [self._stock(row) for row in rows]

    def update_stock_monitor(self, monitor_id: int, **changes: Any) -> StockPriceMonitor:
        allowed = {"market", "symbol", "name", "threshold_price", "is_active", "state"}
        values = {key: value for key, value in changes.items() if key in allowed}
        if not values:
            monitor = self.get_stock_monitor(monitor_id)
            if monitor is None:
                raise ValueError("stock monitor not found")
            return monitor
        if "state" in values:
            _validate(values["state"], STOCK_STATES, "stock monitor state")
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        where = " WHERE id = ?"
        if "state" in values:
            where += " AND is_active = 1"
        cursor = self.conn.execute(f"UPDATE monitoring_stock_monitors SET {assignments}{where}", (*values.values(), monitor_id))
        if "state" in values and cursor.rowcount != 1:
            raise ValueError("stock monitor is inactive or not found")
        monitor = self.get_stock_monitor(monitor_id)
        if monitor is None:
            raise ValueError("stock monitor not found")
        return monitor

    def soft_delete_stock_monitor(self, monitor_id: int) -> StockPriceMonitor:
        return self.update_stock_monitor(monitor_id, is_active=False)

    def pause_stock_monitor(self, monitor_id: int) -> StockPriceMonitor:
        return self.update_stock_monitor(monitor_id, state="paused")

    def resume_stock_monitor(self, monitor_id: int) -> StockPriceMonitor:
        return self.update_stock_monitor(monitor_id, state="armed")

    def claim_price_trigger(self, monitor_id: int, observed_price: float, observed_date: str, triggered_at: str) -> bool:
        started = not self.conn.in_transaction
        try:
            if started:
                self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT * FROM monitoring_stock_monitors WHERE id = ?", (monitor_id,)).fetchone()
            if row is None:
                raise ValueError("stock monitor not found")
            cursor = self.conn.execute(
                "UPDATE monitoring_stock_monitors SET state = 'triggered', last_price = ?, last_price_date = ?, last_triggered_at = ?, updated_at = ? WHERE id = ? AND is_active = 1 AND state = 'armed'",
                (observed_price, observed_date, triggered_at, triggered_at, monitor_id),
            )
            if cursor.rowcount != 1:
                if started:
                    self.conn.commit()
                return False
            self.conn.execute(
                "INSERT INTO monitoring_stock_events (monitor_id, market, symbol, observed_price, threshold_price, observed_date, triggered_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'recorded')",
                (monitor_id, row["market"], row["symbol"], observed_price, row["threshold_price"], observed_date, triggered_at),
            )
            if started:
                self.conn.commit()
            return True
        except Exception:
            if started:
                self.conn.rollback()
            raise

    def rearm_price_monitor(self, monitor_id: int) -> bool:
        cursor = self.conn.execute("UPDATE monitoring_stock_monitors SET state = 'armed', updated_at = ? WHERE id = ? AND is_active = 1 AND state = 'triggered'", (_now(), monitor_id))
        return cursor.rowcount == 1

    def list_stock_events(self, monitor_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM monitoring_stock_events WHERE monitor_id = ? ORDER BY observed_date, id", (monitor_id,)).fetchall()
        return [dict(row) for row in rows]
