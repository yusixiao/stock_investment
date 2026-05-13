"""共享工具函数 — API 超时执行、进度日志、JSON 安全序列化等。"""

import math
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable

logger = logging.getLogger(__name__)

DEFAULT_API_TIMEOUT = 30


def run_with_timeout(fn, *args, timeout: int = DEFAULT_API_TIMEOUT):
    """在独立线程中执行函数，超时则抛出 FutureTimeout。"""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(fn, *args)
        return future.result(timeout=timeout)
    except (FutureTimeout, Exception):
        executor.shutdown(wait=False, cancel_futures=True)
        raise


def safe_json(obj):
    """递归清理 float NaN/Inf 为 None，确保 JSON 序列化安全。"""

    def _clean(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    def _clean_obj(o):
        if isinstance(o, dict):
            return {k: _clean_obj(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_clean_obj(i) for i in o]
        return _clean(o)

    return _clean_obj(obj)


class BackgroundTaskRunner:
    """通用后台任务执行器，封装线程安全的状态管理。

    用法:
        runner = BackgroundTaskRunner()
        runner.start(my_updater_fn, mode="full", force=False)
        status = runner.get_status()
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._status = {"status": "idle", "progress": None, "result": None}

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._status)

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._status["status"] == "running"

    def start(self, task_fn: Callable, **kwargs) -> bool:
        """启动后台任务。task_fn 签名: (on_progress=callback, **kwargs) -> result。
        返回 True 表示启动成功，False 表示已有任务在运行。
        """
        with self._lock:
            if self._status["status"] == "running":
                return False
            self._status = {"status": "running", "progress": None, "result": None}

        def _run():
            def on_progress(current, total, phase):
                with self._lock:
                    self._status["progress"] = {
                        "current": current,
                        "total": total,
                        "phase": phase,
                    }

            try:
                result = task_fn(on_progress=on_progress, **kwargs)
                with self._lock:
                    self._status["status"] = "success"
                    self._status["result"] = result
            except Exception as e:
                logger.exception("后台任务执行失败")
                with self._lock:
                    self._status["status"] = "failed"
                    self._status["result"] = {"error": str(e)}

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return True
