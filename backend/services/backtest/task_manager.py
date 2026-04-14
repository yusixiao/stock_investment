import json
import sqlite3
import threading
import uuid
from datetime import datetime

from config import PORTFOLIO_DB


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(PORTFOLIO_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init_table():
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                task_type TEXT NOT NULL DEFAULT 'screener',
                pipeline_info TEXT,
                start_date TEXT,
                end_date TEXT,
                summary TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL
            )
        """)
        for col, typedef in [("task_type", "TEXT NOT NULL DEFAULT 'screener'"), ("summary", "TEXT"), ("pipeline_info", "TEXT"), ("start_date", "TEXT"), ("end_date", "TEXT"), ("source_task_id", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE backtest_tasks ADD COLUMN {col} {typedef}")
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


_init_table()


class TaskManager:
    def __init__(self):
        self._progress: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_task(self, task_type: str = "screener", pipeline_info: list[dict] | None = None, start_date: str | None = None, end_date: str | None = None, source_task_id: str | None = None) -> str:
        task_id = str(uuid.uuid4())[:8]
        pi_json = json.dumps(pipeline_info, ensure_ascii=False) if pipeline_info else None
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, start_date, end_date, source_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, "running", task_type, pi_json, start_date, end_date, source_task_id, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
        with self._lock:
            self._progress[task_id] = None
        return task_id

    def update_progress(self, task_id: str, current: int, total: int, phase: str = ""):
        with self._lock:
            self._progress[task_id] = {
                "current": current,
                "total": total,
                "phase": phase,
            }

    def _build_summary(self, result: dict) -> str:
        if "screened_symbols" in result:
            items = result["screened_symbols"]
            count = len(items)
            return json.dumps({"screened_count": count}, ensure_ascii=False)
        if "metrics" in result:
            m = result["metrics"]
            return json.dumps({
                "total_return": m.get("total_return"),
                "annual_return": m.get("annual_return"),
                "max_drawdown": m.get("max_drawdown"),
                "trade_count": m.get("trade_count"),
            }, ensure_ascii=False)
        return ""

    def complete_task(self, task_id: str, result: dict):
        summary = self._build_summary(result)
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE backtest_tasks SET status = ?, result = ?, summary = ? WHERE task_id = ?",
                ("success", json.dumps(result, ensure_ascii=False), summary, task_id),
            )
            conn.commit()
        finally:
            conn.close()
        with self._lock:
            self._progress.pop(task_id, None)

    def fail_task(self, task_id: str, error: str):
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE backtest_tasks SET status = ?, error = ? WHERE task_id = ?",
                ("failed", error, task_id),
            )
            conn.commit()
        finally:
            conn.close()
        with self._lock:
            self._progress.pop(task_id, None)

    def get_status(self, task_id: str) -> dict | None:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT status FROM backtest_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        resp = {"task_id": task_id, "status": row["status"]}
        with self._lock:
            prog = self._progress.get(task_id)
            if prog:
                resp["progress"] = prog
        return resp

    def get_result(self, task_id: str) -> dict | None:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT status, result, error, pipeline_info, start_date, end_date, source_task_id FROM backtest_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        result = json.loads(row["result"]) if row["result"] else None
        resp = {
            "task_id": task_id,
            "status": row["status"],
            "result": result,
            "error": row["error"],
        }
        if row["pipeline_info"]:
            try:
                resp["pipeline_info"] = json.loads(row["pipeline_info"])
            except Exception:
                pass
        if row["start_date"]:
            resp["start_date"] = row["start_date"]
        if row["end_date"]:
            resp["end_date"] = row["end_date"]
        if row["source_task_id"]:
            resp["source_task_id"] = row["source_task_id"]
        return resp

    def list_tasks(self) -> list[dict]:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT task_id, status, task_type, summary, created_at, source_task_id FROM backtest_tasks ORDER BY created_at DESC"
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            item = {
                "task_id": r["task_id"],
                "status": r["status"],
                "task_type": r["task_type"],
                "created_at": r["created_at"],
            }
            if r["source_task_id"]:
                item["source_task_id"] = r["source_task_id"]
            if r["summary"]:
                try:
                    item["summary"] = json.loads(r["summary"])
                except Exception:
                    pass
            result.append(item)
        return result


task_manager = TaskManager()
