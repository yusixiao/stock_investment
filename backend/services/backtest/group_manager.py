import json
import sqlite3
import uuid
from datetime import datetime

from config import PORTFOLIO_DB


class GroupManager:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(PORTFOLIO_DB)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_tables(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_groups (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    pipeline TEXT NOT NULL,
                    join_modes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS group_runs (
                    run_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    execution_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step INTEGER DEFAULT 0,
                    steps_result TEXT,
                    final_result TEXT,
                    summary TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (group_id) REFERENCES strategy_groups(group_id)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def create_group(self, name: str, pipeline: list[dict], join_modes: list[str] | None = None) -> str:
        group_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO strategy_groups (group_id, name, pipeline, join_modes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (group_id, name, json.dumps(pipeline, ensure_ascii=False), json.dumps(join_modes or [], ensure_ascii=False), now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return group_id

    def get_group(self, group_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM strategy_groups WHERE group_id = ?", (group_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "group_id": row["group_id"],
            "name": row["name"],
            "pipeline": json.loads(row["pipeline"]),
            "join_modes": json.loads(row["join_modes"]) if row["join_modes"] else [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_groups(self) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM strategy_groups ORDER BY updated_at DESC").fetchall()
            result = []
            for row in rows:
                group = {
                    "group_id": row["group_id"],
                    "name": row["name"],
                    "pipeline": json.loads(row["pipeline"]),
                    "join_modes": json.loads(row["join_modes"]) if row["join_modes"] else [],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                run_row = conn.execute(
                    "SELECT count(*) as cnt, max(created_at) as last_run FROM group_runs WHERE group_id = ?",
                    (row["group_id"],),
                ).fetchone()
                group["run_count"] = run_row["cnt"]
                group["last_run"] = run_row["last_run"]
                result.append(group)
        finally:
            conn.close()
        return result

    def update_group(self, group_id: str, name: str | None = None, pipeline: list[dict] | None = None, join_modes: list[str] | None = None):
        conn = self._get_conn()
        try:
            updates = []
            params = []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if pipeline is not None:
                updates.append("pipeline = ?")
                params.append(json.dumps(pipeline, ensure_ascii=False))
            if join_modes is not None:
                updates.append("join_modes = ?")
                params.append(json.dumps(join_modes, ensure_ascii=False))
            if updates:
                updates.append("updated_at = ?")
                params.append(datetime.now().isoformat())
                params.append(group_id)
                conn.execute(f"UPDATE strategy_groups SET {', '.join(updates)} WHERE group_id = ?", params)
                conn.commit()
        finally:
            conn.close()

    def delete_group(self, group_id: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM group_runs WHERE group_id = ?", (group_id,))
            conn.execute("DELETE FROM strategy_groups WHERE group_id = ?", (group_id,))
            conn.commit()
        finally:
            conn.close()

    def create_run(self, group_id: str, start_date: str | None, end_date: str | None, execution_mode: str) -> str:
        run_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO group_runs (run_id, group_id, start_date, end_date, execution_mode, status, current_step, steps_result, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, group_id, start_date, end_date, execution_mode, "running", 0, "[]", now),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM group_runs WHERE run_id = ?", (run_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "group_id": row["group_id"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "execution_mode": row["execution_mode"],
            "status": row["status"],
            "current_step": row["current_step"],
            "steps_result": json.loads(row["steps_result"]) if row["steps_result"] else [],
            "final_result": json.loads(row["final_result"]) if row["final_result"] else None,
            "summary": json.loads(row["summary"]) if row["summary"] else None,
            "error": row["error"],
            "created_at": row["created_at"],
        }

    def list_runs(self, group_id: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM group_runs WHERE group_id = ? ORDER BY created_at DESC", (group_id,)).fetchall()
        finally:
            conn.close()
        result = []
        for row in rows:
            result.append({
                "run_id": row["run_id"],
                "group_id": row["group_id"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "execution_mode": row["execution_mode"],
                "status": row["status"],
                "current_step": row["current_step"],
                "summary": json.loads(row["summary"]) if row["summary"] else None,
                "error": row["error"],
                "created_at": row["created_at"],
            })
        return result

    def update_run_step(self, run_id: str, step: int, steps_result: list[dict]):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE group_runs SET current_step = ?, steps_result = ? WHERE run_id = ?",
                (step, json.dumps(steps_result, ensure_ascii=False), run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_run_status(self, run_id: str, status: str, final_result: dict | None = None, summary: dict | None = None, error: str | None = None):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE group_runs SET status = ?, final_result = ?, summary = ?, error = ? WHERE run_id = ?",
                (status, json.dumps(final_result, ensure_ascii=False) if final_result else None, json.dumps(summary, ensure_ascii=False) if summary else None, error, run_id),
            )
            conn.commit()
        finally:
            conn.close()


group_manager_instance = GroupManager()
