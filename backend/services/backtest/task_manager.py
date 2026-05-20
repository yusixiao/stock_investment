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
        strategy_class: str | None = None,
        params: dict | None = None,
        log_dir: str | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())[:8]
        # merge-strategies 单策略模型: 显式传 strategy_class/params 时
        # 覆盖/构造 pipeline_info = {strategy_class, params}
        if strategy_class is not None:
            pipeline_info = {"strategy_class": strategy_class, "params": params or {}}
        pi_json = (
            json.dumps(pipeline_info, ensure_ascii=False) if pipeline_info else None
        )
        # log_dir 默认按 task_id 派生(可外部覆盖)
        effective_log_dir = log_dir or f"data/logs/backtest/{task_id}/"
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, start_date, end_date, source_task_id, created_at, log_dir) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    "running",
                    task_type,
                    pi_json,
                    start_date,
                    end_date,
                    source_task_id,
                    datetime.now().isoformat(),
                    effective_log_dir,
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
                    "total_trades": m.get("total_trades"),
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
        # 软删: 同步写 is_deleted 与遗留 deleted 列, 兼容旧查询
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE backtest_tasks SET is_deleted = 1, deleted = 1 WHERE task_id = ?",
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
                "SELECT status, result, error, pipeline_info, start_date, end_date, source_task_id, log_dir FROM backtest_tasks WHERE task_id = ?",
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
        if row["log_dir"]:
            resp["log_dir"] = row["log_dir"]
        return resp

    def list_tasks(
        self,
        show_deleted: bool = False,
        include_deleted: bool | None = None,
    ) -> list[dict]:
        # include_deleted 为 plan 命名;show_deleted 是历史兼容别名,二者任一为真即返回全部
        effective_include = bool(show_deleted) or bool(include_deleted)
        conn = self._get_conn()
        try:
            base_cols = "task_id, status, task_type, summary, created_at, source_task_id, is_deleted, pipeline_info, start_date, end_date"
            if effective_include:
                rows = conn.execute(
                    f"SELECT {base_cols} FROM backtest_tasks ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {base_cols} FROM backtest_tasks WHERE is_deleted = 0 ORDER BY created_at DESC"
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
                "deleted": bool(r["is_deleted"]),
                "start_date": r["start_date"],
                "end_date": r["end_date"],
            }
            if r["source_task_id"]:
                item["source_task_id"] = r["source_task_id"]
            if r["summary"]:
                try:
                    item["summary"] = json.loads(r["summary"])
                except Exception:
                    pass
            if r["pipeline_info"]:
                try:
                    item["pipeline_info"] = json.loads(r["pipeline_info"])
                except Exception:
                    pass
            result.append(item)
        return result


task_manager = TaskManager()
