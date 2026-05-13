import json
import sqlite3
import threading
import uuid
from datetime import datetime

from config import PORTFOLIO_DB


class TaskManager:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(PORTFOLIO_DB)
        self._progress: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._init_table()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self):
        conn = self._get_conn()
        try:
            from services.db_schema import init_backtest_tables

            init_backtest_tables(conn)
            conn.execute(
                "UPDATE backtest_tasks SET status = ?, error = ? WHERE status = ?",
                ("failed", "服务重启，任务中断", "running"),
            )
            conn.commit()
        finally:
            conn.close()

    def create_task(
        self,
        task_type: str = "screener",
        pipeline_info: list[dict] | dict | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        source_task_id: str | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())[:8]
        pi_json = (
            json.dumps(pipeline_info, ensure_ascii=False) if pipeline_info else None
        )
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, start_date, end_date, source_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    "running",
                    task_type,
                    pi_json,
                    start_date,
                    end_date,
                    source_task_id,
                    datetime.now().isoformat(),
                ),
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
            return json.dumps(
                {
                    "total_return": m.get("total_return"),
                    "annual_return": m.get("annual_return"),
                    "max_drawdown": m.get("max_drawdown"),
                    "trade_count": m.get("trade_count"),
                },
                ensure_ascii=False,
            )
        return ""

    def complete_task(self, task_id: str, result: dict):
        summary = self._build_summary(result)
        conn = self._get_conn()
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

    def delete_task(self, task_id: str):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE backtest_tasks SET deleted = 1 WHERE task_id = ?",
                (task_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def fail_task(self, task_id: str, error: str):
        conn = self._get_conn()
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
        conn = self._get_conn()
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
        conn = self._get_conn()
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

    def list_tasks(self, show_deleted: bool = False) -> list[dict]:
        conn = self._get_conn()
        try:
            if show_deleted:
                rows = conn.execute(
                    "SELECT task_id, status, task_type, summary, created_at, source_task_id, deleted FROM backtest_tasks ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT task_id, status, task_type, summary, created_at, source_task_id, deleted FROM backtest_tasks WHERE deleted = 0 ORDER BY created_at DESC"
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
                "deleted": bool(r["deleted"]),
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
