import threading
from fastapi import APIRouter

from services.valuation_updater import run_valuation_update

router = APIRouter(prefix="/api/valuation", tags=["valuation"])

_status = {"status": "idle", "progress": None, "result": None}
_lock = threading.Lock()


def run_update_in_background(mode: str, force: bool = False):
    def _task():
        _status["status"] = "running"
        _status["progress"] = None
        _status["result"] = None

        def on_progress(current, total, phase):
            _status["progress"] = {"current": current, "total": total, "phase": phase}

        try:
            result = run_valuation_update(mode=mode, force=force, on_progress=on_progress)
            _status["status"] = "success"
            _status["result"] = result
        except Exception as e:
            _status["status"] = "failed"
            _status["result"] = {"error": str(e)}

    t = threading.Thread(target=_task, daemon=True)
    t.start()


@router.post("/update")
def api_trigger_valuation_update(body: dict = None):
    body = body or {}
    mode = body.get("mode", "full")
    force = body.get("force", False)
    if _status["status"] == "running":
        return {"message": "already running"}
    run_update_in_background(mode, force)
    return {"message": "valuation update started", "mode": mode}


@router.get("/update/status")
def api_valuation_status():
    return dict(_status)
