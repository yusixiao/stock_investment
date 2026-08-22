import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from config import PORTFOLIO_DB
from services.backtest.task_progress import TaskProgressStore
from services.backtest.task_repository import TaskRepository
from services.backtest.task_result_codec import TaskResultCodec


class TaskManager:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(PORTFOLIO_DB)
        self._progress_store = TaskProgressStore()
        self._result_codec = TaskResultCodec()
        self._repository = TaskRepository(self._db_path)

    @classmethod
    def _from_collaborators(cls, repository, result_codec, progress_store):
        manager = cls.__new__(cls)
        manager._db_path = getattr(repository, "_db_path", None)
        manager._repository = repository
        manager._result_codec = result_codec
        manager._progress_store = progress_store
        return manager

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
        trigger_source: str | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())[:8]
        # merge-strategies 单策略模型: 显式传 strategy_class/params 时
        # 覆盖/构造 pipeline_info = {strategy_class, strategy_name?, params, frequency?, symbols?, market?}
        if strategy_class is not None:
            pipeline_info = dict(pipeline_info or {})
            pipeline_info.update({"strategy_class": strategy_class, "params": params or {}})
            if strategy_name:
                pipeline_info["strategy_name"] = strategy_name
            if frequency is not None:
                pipeline_info["frequency"] = frequency
            if symbols is not None:
                pipeline_info["symbols"] = symbols
            if market is not None:
                pipeline_info["market"] = market
        pi_json = (
            self._result_codec.encode(pipeline_info) if pipeline_info else None
        )
        # log_dir 默认按 task_id 派生(可外部覆盖)
        effective_log_dir = (
            str(Path(log_dir) / task_id) if log_dir else f"logs/backtest/{task_id}/"
        )
        self._repository.create_task_row(
            task_id=task_id,
            task_type=task_type,
            pipeline_info=pi_json,
            start_date=start_date,
            end_date=end_date,
            source_task_id=source_task_id,
            created_at=datetime.now().isoformat(),
            log_dir=effective_log_dir,
            trigger_source=trigger_source,
        )
        self._progress_store.remove(task_id)
        return task_id

    def update_task_metadata(
        self,
        task_id: str,
        *,
        strategy_name: str | None = None,
        params: dict | None = None,
        frequency: str | None = None,
    ) -> None:
        updates = {}
        if strategy_name is not None:
            updates["strategy_name"] = strategy_name
        if params is not None:
            updates["params"] = params
        if frequency is not None:
            updates["frequency"] = frequency
        self._repository.update_task_metadata(task_id, updates)

    def update_progress(self, task_id: str, current: int, total: int, phase: str = ""):
        self._progress_store.update(task_id, current, total, phase)

    def complete_task(self, task_id: str, result: dict):
        summary = self._result_codec.build_summary(result)
        # 若 result 含 date_range(scan-radar 结果),回写到 start_date/end_date 列,
        # 让历史记录列表与一般回测任务统一展示
        date_start, date_end = self._result_codec.date_range(result)
        self._repository.update_task_result(
            task_id,
            result=self._result_codec.encode(result),
            summary=summary,
            date_start=date_start,
            date_end=date_end,
        )
        self._progress_store.remove(task_id)

    def delete_task(self, task_id: str):
        self._repository.delete_task(task_id)
        self._progress_store.remove(task_id)

    def fail_task(self, task_id: str, error: str):
        self._repository.fail_task(task_id, error)
        self._progress_store.remove(task_id)

    def get_status(self, task_id: str) -> dict | None:
        status = self._repository.get_status(task_id)
        if status is None:
            return None
        resp = {"task_id": task_id, "status": status}
        prog = self._progress_store.get(task_id)
        if prog:
            resp["progress"] = prog
        return resp

    def get_result(self, task_id: str, connection: sqlite3.Connection | None = None) -> dict | None:
        row = self._repository.get_result_row(task_id, connection=connection)
        if row is None:
            return None
        result = self._result_codec.decode(row["result"])
        resp = {
            "task_id": task_id,
            "status": row["status"],
            "result": result,
            "error": row["error"],
            "execution_status": row["execution_status"],
            "execution_account_id": row["execution_account_id"],
            "trigger_source": row["trigger_source"],
        }
        if row["pipeline_info"]:
            decoded, pipeline_info = self._result_codec.decode_with_status(
                row["pipeline_info"]
            )
            if decoded:
                resp["pipeline_info"] = pipeline_info
        if row["start_date"]:
            resp["start_date"] = row["start_date"]
        if row["end_date"]:
            resp["end_date"] = row["end_date"]
        if row["source_task_id"]:
            resp["source_task_id"] = row["source_task_id"]
        if row["log_dir"]:
            resp["log_dir"] = row["log_dir"]
        return resp

    def set_execution_account(
        self, task_id: str, account_id: int, connection: sqlite3.Connection | None = None
    ) -> dict:
        return self._repository.set_execution_account(task_id, account_id, connection)

    def clear_execution_account(
        self, task_id: str, connection: sqlite3.Connection | None = None
    ) -> dict:
        return self._repository.clear_execution_account(task_id, connection)

    def list_tasks(
        self,
        show_deleted: bool = False,
        include_deleted: bool | None = None,
    ) -> list[dict]:
        # include_deleted 为 plan 命名;show_deleted 是历史兼容别名,二者任一为真即返回全部
        effective_include = bool(show_deleted) or bool(include_deleted)
        rows = self._repository.list_task_rows(include_deleted=effective_include)
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
                "trigger_source": r["trigger_source"],
            }
            if r["source_task_id"]:
                item["source_task_id"] = r["source_task_id"]
            if r["summary"]:
                decoded, summary = self._result_codec.decode_with_status(r["summary"])
                if decoded:
                    item["summary"] = summary
            if r["pipeline_info"]:
                decoded, pipeline_info = self._result_codec.decode_with_status(
                    r["pipeline_info"]
                )
                if decoded:
                    item["pipeline_info"] = pipeline_info
            result.append(item)
        return result


task_manager = TaskManager()
