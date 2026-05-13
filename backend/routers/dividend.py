from fastapi import APIRouter

from services.dividend_updater import run_dividend_update
from services.api_utils import BackgroundTaskRunner

router = APIRouter(prefix="/api/dividend", tags=["dividend"])

_runner = BackgroundTaskRunner()


@router.post("/update")
def api_trigger_dividend_update(body: dict = None):
    body = body or {}
    mode = body.get("mode", "full")
    force = body.get("force", False)
    if not _runner.start(run_dividend_update, mode=mode, force=force):
        return {"message": "already running"}
    return {"message": "dividend update started", "mode": mode}


@router.get("/update/status")
def api_dividend_status():
    return _runner.get_status()
