"""元数据相关 API — 流通股数等。"""

import threading
from fastapi import APIRouter

from services.circulating_shares import update_circulating_shares, get_circulating_shares

router = APIRouter(prefix="/api/meta", tags=["meta"])

_status = {"status": "idle", "result": None, "phase": None}


@router.post("/circulating-shares/update")
def api_update_circulating_shares():
    """触发流通股数快照更新（后台执行）。"""
    if _status["status"] == "running":
        return {"message": "already running", "phase": _status["phase"]}

    def _task():
        _status["status"] = "running"
        _status["result"] = None
        _status["phase"] = "获取数据中..."
        try:
            result = update_circulating_shares(
                on_phase=lambda p: _status.update({"phase": p})
            )
            _status["status"] = "success"
            _status["result"] = result
            _status["phase"] = "完成"
        except Exception as e:
            _status["status"] = "failed"
            _status["result"] = {"error": str(e)}
            _status["phase"] = None

    t = threading.Thread(target=_task, daemon=True)
    t.start()
    return {"message": "started"}


@router.get("/circulating-shares/status")
def api_circulating_shares_status():
    """查询更新状态。"""
    return {"status": _status["status"], "phase": _status["phase"], "result": _status["result"]}


@router.get("/circulating-shares")
def api_get_circulating_shares():
    """获取当前流通股数快照。"""
    df = get_circulating_shares()
    if df is None:
        return {"data": [], "update_date": None}
    update_date = df["update_date"].iloc[0] if len(df) > 0 else None
    records = df[["symbol", "circulating_shares"]].to_dict(orient="records")
    return {"data": records, "update_date": update_date}
