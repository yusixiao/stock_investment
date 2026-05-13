from fastapi import APIRouter

from services.financial_updater import run_financial_update
from services.api_utils import BackgroundTaskRunner

router = APIRouter(prefix="/api/financial", tags=["financial"])

_runner = BackgroundTaskRunner()


@router.post("/update")
def api_trigger_financial_update(body: dict = None):
    body = body or {}
    mode = body.get("mode", "full")
    if not _runner.start(run_financial_update, mode=mode):
        return {"message": "already running"}
    return {"message": "financial update started", "mode": mode}


@router.get("/update/status")
def api_financial_status():
    return _runner.get_status()
