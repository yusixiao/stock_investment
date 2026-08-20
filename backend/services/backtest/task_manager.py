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
        strategy_name: str | None = None,
        params: dict | None = None,
        frequency: str | None = None,
        symbols: list[str] | None = None,
        market: str | None = None,
        log_dir: str | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())[:8]
        # merge-strategies 单策略模型: 显式传 strategy_class/params 时
        # 覆盖/构造 pipeline_info = {strategy_class, strategy_name?, params, frequency?, symbols?, market?}
        if strategy_class is not None:
            pipeline_info = {"strategy_class": strategy_class, "params": params or {}}
            if strategy_name:
                pipeline_info["strategy_name"] = strategy_name
            if frequency is not None:
                pipeline_info["frequency"] = frequency
            if symbols is not None:
                pipeline_info["symbols"] = symbols
            if market is not None:
                pipeline_info["market"] = market
        pi_json = (
            json.dumps(pipeline_info, ensure_ascii=False) if pipeline_info else None
        )
        # log_dir 默认按 task_id 派生(可外部覆盖)
        effective_log_dir = log_dir or f"logs/backtest/{task_id}/"
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
        if "hits" in result and "total_scanned" in result:
            return json.dumps(
                {
                    "hit_count": len(result.get("hits") or []),
                    "total_scanned": result.get("total_scanned"),
                    "lookback_used": result.get("lookback_used"),
                },
                ensure_ascii=False,
            )
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
        # 若 result 含 date_range(scan-radar 结果),回写到 start_date/end_date 列,
        # 让历史记录列表与一般回测任务统一展示
        dr = result.get("date_range") if isinstance(result, dict) else None
        date_start = (dr or {}).get("start") if isinstance(dr, dict) else None
        date_end = (dr or {}).get("end") if isinstance(dr, dict) else None
        conn = self._get_conn()
        try:
            if date_start and date_end:
                conn.execute(
                    "UPDATE backtest_tasks SET status = ?, result = ?, summary = ?, "
                    "start_date = COALESCE(NULLIF(start_date, ''), ?), "
                    "end_date = COALESCE(NULLIF(end_date, ''), ?) "
                    "WHERE task_id = ?",
                    (
                        "success",
                        json.dumps(result, ensure_ascii=False),
                        summary,
                        date_start,
                        date_end,
                        task_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE backtest_tasks SET status = ?, result = ?, summary = ? WHERE task_id = ?",
                    (
                        "success",
                        json.dumps(result, ensure_ascii=False),
                        summary,
                        task_id,
                    ),
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
                "SELECT status, result, error, pipeline_info, start_date, end_date, source_task_id, log_dir, execution_status, execution_account_id FROM backtest_tasks WHERE task_id = ?",
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
            "execution_status": row["execution_status"],
            "execution_account_id": row["execution_account_id"],
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

    def set_execution_account(self, task_id: str, account_id: int) -> dict:
        """将任务标记为某账户的唯一活动策略关联。"""
        conn = self._get_conn()
        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conflict = conn.execute(
                    "SELECT task_id FROM backtest_tasks "
                    "WHERE execution_account_id = ? AND execution_status = 'active' "
                    "AND task_id != ?",
                    (account_id, task_id),
                ).fetchone()
                if conflict:
                    raise ValueError(
                        f"account {account_id} is already associated with task {conflict['task_id']}"
                    )
                updated = conn.execute(
                    "UPDATE backtest_tasks SET execution_status = 'active', "
                    "execution_account_id = ? WHERE task_id = ?",
                    (account_id, task_id),
                )
                if updated.rowcount == 0:
                    raise ValueError(f"task {task_id} not found")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        finally:
            conn.close()
        return {
            "task_id": task_id,
            "execution_status": "active",
            "execution_account_id": account_id,
        }

    def clear_execution_account(self, task_id: str) -> dict:
        conn = self._get_conn()
        try:
            updated = conn.execute(
                "UPDATE backtest_tasks SET execution_status = 'inactive', "
                "execution_account_id = NULL WHERE task_id = ?",
                (task_id,),
            )
            if updated.rowcount == 0:
                raise ValueError(f"task {task_id} not found")
            conn.commit()
        finally:
            conn.close()
        return {
            "task_id": task_id,
            "execution_status": "inactive",
            "execution_account_id": None,
        }

    def list_tasks(
        self,
        show_deleted: bool = False,
        include_deleted: bool | None = None,
    ) -> list[dict]:
        # include_deleted 为 plan 命名;show_deleted 是历史兼容别名,二者任一为真即返回全部
        effective_include = bool(show_deleted) or bool(include_deleted)
        conn = self._get_conn()
        try:
            base_cols = "task_id, status, task_type, summary, created_at, source_task_id, is_deleted, pipeline_info, start_date, end_date, execution_status, execution_account_id"
            # 旧版/测试任务: pipeline_info 为空(NULL 或 '') → 不在历史页展示
            # show_deleted=True 时仍返回全部以便 debug
            if effective_include:
                rows = conn.execute(
                    f"SELECT {base_cols} FROM backtest_tasks ORDER BY execution_status = 'active' DESC, created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {base_cols} FROM backtest_tasks "
                    f"WHERE is_deleted = 0 AND pipeline_info IS NOT NULL AND pipeline_info != '' "
                    f"ORDER BY execution_status = 'active' DESC, created_at DESC"
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
                "execution_status": r["execution_status"],
                "execution_account_id": r["execution_account_id"],
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
