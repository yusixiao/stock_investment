from fastapi import APIRouter

from services.valuation_updater import run_valuation_update
from services.api_utils import BackgroundTaskRunner

router = APIRouter(prefix="/api/valuation", tags=["valuation"])

_runner = BackgroundTaskRunner()


@router.post("/update")
def api_trigger_valuation_update(body: dict = None):
    body = body or {}
    mode = body.get("mode", "full")
    force = body.get("force", False)
    if not _runner.start(run_valuation_update, mode=mode, force=force):
        return {"message": "already running"}
    return {"message": "valuation update started", "mode": mode}


@router.get("/update/status")
def api_valuation_status():
    return _runner.get_status()
