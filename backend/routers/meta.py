"""元数据相关 API — 流通股数等。"""

from fastapi import APIRouter

from services.circulating_shares import (
    update_circulating_shares,
    get_circulating_shares,
)
from services.api_utils import BackgroundTaskRunner

router = APIRouter(prefix="/api/meta", tags=["meta"])

_runner = BackgroundTaskRunner()


def _run_circulating_update(on_progress=None, **kwargs):
    """适配 BackgroundTaskRunner 的签名，将 on_progress 映射为 on_phase。"""

    def on_phase(p):
        if on_progress:
            on_progress(0, 0, p)

    return update_circulating_shares(on_phase=on_phase)


@router.post("/circulating-shares/update")
def api_update_circulating_shares():
    """触发流通股数快照更新（后台执行）。"""
    if not _runner.start(_run_circulating_update):
        status = _runner.get_status()
        return {
            "message": "already running",
            "phase": status.get("progress", {}).get("phase"),
        }
    return {"message": "started"}


@router.get("/circulating-shares/status")
def api_circulating_shares_status():
    """查询更新状态。"""
    status = _runner.get_status()
    progress = status.get("progress") or {}
    return {
        "status": status["status"],
        "phase": progress.get("phase"),
        "result": status["result"],
    }


@router.get("/circulating-shares")
def api_get_circulating_shares():
    """获取当前流通股数快照。"""
    df = get_circulating_shares()
    if df is None:
        return {"data": [], "update_date": None}
    update_date = df["update_date"].iloc[0] if len(df) > 0 else None
    records = df[["symbol", "circulating_shares"]].to_dict(orient="records")
    return {"data": records, "update_date": update_date}
