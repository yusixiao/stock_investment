import threading
from fastapi import APIRouter

from services.financial_updater import run_financial_update

router = APIRouter(prefix="/api/financial", tags=["financial"])

_status = {"status": "idle", "progress": None, "result": None}
_lock = threading.Lock()


def run_update_in_background(mode: str):
    def _task():
        _status["status"] = "running"
        _status["progress"] = None
        _status["result"] = None

        def on_progress(current, total, phase):
            _status["progress"] = {"current": current, "total": total, "phase": phase}

        try:
            result = run_financial_update(mode=mode, on_progress=on_progress)
            _status["status"] = "success"
            _status["result"] = result
        except Exception as e:
            _status["status"] = "failed"
            _status["result"] = {"error": str(e)}

    t = threading.Thread(target=_task, daemon=True)
    t.start()


@router.post("/update")
def api_trigger_financial_update(body: dict = None):
    body = body or {}
    mode = body.get("mode", "full")
    if _status["status"] == "running":
        return {"message": "already running"}
    run_update_in_background(mode)
    return {"message": "financial update started", "mode": mode}


@router.get("/update/status")
def api_financial_status():
    return dict(_status)
