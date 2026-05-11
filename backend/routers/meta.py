"""元数据相关 API — 流通股数等。"""

import threading
from fastapi import APIRouter

from services.circulating_shares import update_circulating_shares, get_circulating_shares

router = APIRouter(prefix="/api/meta", tags=["meta"])

_status = {"status": "idle", "result": None}


@router.post("/circulating-shares/update")
def api_update_circulating_shares():
    """触发流通股数快照更新（后台执行）。"""
    if _status["status"] == "running":
        return {"message": "already running"}

    def _task():
        _status["status"] = "running"
        _status["result"] = None
        try:
            result = update_circulating_shares()
            _status["status"] = "success"
            _status["result"] = result
        except Exception as e:
            _status["status"] = "failed"
            _status["result"] = {"error": str(e)}

    t = threading.Thread(target=_task, daemon=True)
    t.start()
    return {"message": "started"}


@router.get("/circulating-shares/status")
def api_circulating_shares_status():
    """查询更新状态。"""
    return _status


@router.get("/circulating-shares")
def api_get_circulating_shares():
    """获取当前流通股数快照。"""
    df = get_circulating_shares()
    if df is None:
        return {"data": [], "update_date": None}
    update_date = df["update_date"].iloc[0] if len(df) > 0 else None
    records = df[["symbol", "circulating_shares"]].to_dict(orient="records")
    return {"data": records, "update_date": update_date}
