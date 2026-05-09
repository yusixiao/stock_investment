import threading
from fastapi import APIRouter

from services.data_updater import (
    run_incremental_update,
    get_update_status,
    get_update_logs,
    UpdateResult,
    _current_status,
    _current_result,
)
import services.data_updater as updater_module

router = APIRouter(prefix="/api/data", tags=["data"])

_update_lock = threading.Lock()


def run_update_task(trigger: str = "manual"):
    if not _update_lock.acquire(blocking=False):
        return
    try:
        updater_module._current_status = "running"
        updater_module._current_result = None
        result = run_incremental_update(trigger=trigger)
        updater_module._current_status = "success"
        updater_module._current_result = result
    except Exception as e:
        updater_module._current_status = "failed"
        updater_module._current_result = UpdateResult(
            errors=[str(e)],
        )
    finally:
        _update_lock.release()


@router.post("/update")
def api_trigger_update():
    t = threading.Thread(target=run_update_task, args=("manual",), daemon=True)
    t.start()
    return {"message": "incremental update started"}


@router.get("/update/status")
def api_update_status():
    return get_update_status()


@router.get("/update/logs")
def api_update_logs(limit: int = 20):
    return get_update_logs(limit=limit)
