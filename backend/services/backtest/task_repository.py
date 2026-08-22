import json
import sqlite3

from datetime import datetime


class TaskRepository:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_table()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self) -> None:
        from services.db_schema import init_backtest_tables

        conn = self._get_conn()
        try:
            init_backtest_tables(conn)
            conn.execute(
                "UPDATE backtest_tasks SET status = ?, error = ? WHERE status = ?",
                ("failed", "服务重启，任务中断", "running"),
            )
            conn.commit()
        finally:
            conn.close()

    def create_task_row(
        self,
        *,
        task_id: str,
        task_type: str,
        pipeline_info: str | None,
        start_date: str | None,
        end_date: str | None,
        source_task_id: str | None,
        created_at: str | None = None,
        log_dir: str | None,
        trigger_source: str | None,
    ) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, start_date, end_date, source_task_id, created_at, log_dir, trigger_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    "running",
                    task_type,
                    pipeline_info,
                    start_date,
                    end_date,
                    source_task_id,
                    created_at or datetime.now().isoformat(),
                    log_dir,
                    trigger_source,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def update_task_metadata(self, task_id: str, pipeline_info: str | dict) -> None:
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT pipeline_info FROM backtest_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                conn.commit()
                return

            try:
                info = json.loads(row["pipeline_info"] or "{}")
            except (TypeError, ValueError):
                info = {}
            if not isinstance(info, dict):
                info = {}

            if isinstance(pipeline_info, dict):
                info.update(pipeline_info)
                pipeline_info = json.dumps(info, ensure_ascii=False)
            conn.execute(
                "UPDATE backtest_tasks SET pipeline_info = ? WHERE task_id = ?",
                (pipeline_info, task_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_task_result(
        self,
        task_id: str,
        *,
        result: str,
        summary: str,
        date_start: str | None = None,
        date_end: str | None = None,
    ) -> None:
        conn = self._get_conn()
        try:
            if date_start and date_end:
                conn.execute(
                    "UPDATE backtest_tasks SET status = ?, result = ?, summary = ?, "
                    "start_date = COALESCE(NULLIF(start_date, ''), ?), "
                    "end_date = COALESCE(NULLIF(end_date, ''), ?) WHERE task_id = ?",
                    ("success", result, summary, date_start, date_end, task_id),
                )
            else:
                conn.execute(
                    "UPDATE backtest_tasks SET status = ?, result = ?, summary = ? WHERE task_id = ?",
                    ("success", result, summary, task_id),
                )
            conn.commit()
        finally:
            conn.close()

    def fail_task(self, task_id: str, error: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE backtest_tasks SET status = ?, error = ? WHERE task_id = ?",
                ("failed", error, task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_status(self, task_id: str) -> str | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT status FROM backtest_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return row["status"] if row else None
        finally:
            conn.close()

    def get_result_row(
        self, task_id: str, connection: sqlite3.Connection | None = None
    ) -> sqlite3.Row | None:
        owns_connection = connection is None
        conn = connection or self._get_conn()
        try:
            return conn.execute(
                "SELECT status, result, error, summary, pipeline_info, start_date, end_date, source_task_id, log_dir, trigger_source, execution_status, execution_account_id, is_deleted, deleted FROM backtest_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        finally:
            if owns_connection:
                conn.close()

    def list_task_rows(self, include_deleted: bool = False) -> list[sqlite3.Row]:
        conn = self._get_conn()
        try:
            base_cols = "task_id, status, task_type, summary, created_at, source_task_id, is_deleted, pipeline_info, start_date, end_date, trigger_source, execution_status, execution_account_id"
            if include_deleted:
                return conn.execute(
                    f"SELECT {base_cols} FROM backtest_tasks ORDER BY execution_status = 'active' DESC, created_at DESC"
                ).fetchall()
            return conn.execute(
                f"SELECT {base_cols} FROM backtest_tasks WHERE is_deleted = 0 AND pipeline_info IS NOT NULL AND pipeline_info != '' ORDER BY execution_status = 'active' DESC, created_at DESC"
            ).fetchall()
        finally:
            conn.close()

    def delete_task(self, task_id: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE backtest_tasks SET is_deleted = 1, deleted = 1 WHERE task_id = ?",
                (task_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def set_execution_account(
        self, task_id: str, account_id: int, connection: sqlite3.Connection | None = None
    ) -> dict:
        owns_connection = connection is None
        conn = connection or self._get_conn()
        try:
            try:
                if owns_connection:
                    conn.execute("BEGIN IMMEDIATE")
                conflict = conn.execute(
                    "SELECT task_id FROM backtest_tasks WHERE execution_account_id = ? AND execution_status = 'active' AND task_id != ?",
                    (account_id, task_id),
                ).fetchone()
                if conflict:
                    raise ValueError(
                        f"account {account_id} is already associated with task {conflict['task_id']}"
                    )
                updated = conn.execute(
                    "UPDATE backtest_tasks SET execution_status = 'active', execution_account_id = ? WHERE task_id = ?",
                    (account_id, task_id),
                )
                if updated.rowcount == 0:
                    raise ValueError(f"task {task_id} not found")
                if owns_connection:
                    conn.commit()
            except Exception:
                if owns_connection:
                    conn.rollback()
                raise
        finally:
            if owns_connection:
                conn.close()
        return {"task_id": task_id, "execution_status": "active", "execution_account_id": account_id}

    def clear_execution_account(
        self, task_id: str, connection: sqlite3.Connection | None = None
    ) -> dict:
        owns_connection = connection is None
        conn = connection or self._get_conn()
        try:
            updated = conn.execute(
                "UPDATE backtest_tasks SET execution_status = 'inactive', execution_account_id = NULL WHERE task_id = ?",
                (task_id,),
            )
            if updated.rowcount == 0:
                raise ValueError(f"task {task_id} not found")
            if owns_connection:
                conn.commit()
        finally:
            if owns_connection:
                conn.close()
        return {"task_id": task_id, "execution_status": "inactive", "execution_account_id": None}
