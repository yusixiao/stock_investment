import threading
import uuid
from datetime import datetime


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_task(self) -> str:
        task_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._tasks[task_id] = {
                "status": "running",
                "result": None,
                "error": None,
                "progress": None,
                "created_at": datetime.now().isoformat(),
            }
        return task_id

    def update_progress(self, task_id: str, current: int, total: int, phase: str = ""):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["progress"] = {
                    "current": current,
                    "total": total,
                    "phase": phase,
                }

    def complete_task(self, task_id: str, result: dict):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "success"
                self._tasks[task_id]["result"] = result
                self._tasks[task_id]["progress"] = None

    def fail_task(self, task_id: str, error: str):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "failed"
                self._tasks[task_id]["error"] = error
                self._tasks[task_id]["progress"] = None

    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            resp = {"task_id": task_id, "status": task["status"]}
            if task["progress"]:
                resp["progress"] = task["progress"]
            return resp

    def get_result(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return {
                "task_id": task_id,
                "status": task["status"],
                "result": task["result"],
                "error": task["error"],
            }

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return [
                {"task_id": tid, "status": t["status"], "created_at": t["created_at"]}
                for tid, t in sorted(self._tasks.items(), key=lambda x: x[1]["created_at"], reverse=True)
            ]


task_manager = TaskManager()
