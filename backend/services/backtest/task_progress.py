import threading


class TaskProgressStore:
    def __init__(self):
        self._progress: dict[str, dict | None] = {}
        self._lock = threading.Lock()

    def update(self, task_id: str, current: int, total: int, phase: str = ""):
        with self._lock:
            self._progress[task_id] = {
                "current": current,
                "total": total,
                "phase": phase,
            }

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            progress = self._progress.get(task_id)
            return dict(progress) if progress is not None else None

    def remove(self, task_id: str):
        with self._lock:
            self._progress.pop(task_id, None)
