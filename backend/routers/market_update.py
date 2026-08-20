"""
市场数据增量更新 API — 手动触发 / 查看进度
"""

import threading
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/market-update", tags=["market-update"])


class UpdateRequest(BaseModel):
    market: Optional[str] = None  # None = 全部市场, "A" / "HK" / "US" = 单市场


@router.post("/trigger")
def trigger_update(req: UpdateRequest = UpdateRequest()):
    """手动触发增量更新（后台线程执行）"""
    from services.market_data.refresh_runner import RefreshRunner
    from services.market_data.refresh_state import RefreshAlreadyRunning

    if req.market and req.market not in ("A", "HK", "US"):
        raise HTTPException(status_code=400, detail=f"Invalid market: {req.market}")
    try:
        record = RefreshRunner().start(
            "manual", [req.market] if req.market else None
        )
    except RefreshAlreadyRunning as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "Market refresh already in progress", "refresh_id": exc.refresh_id},
        ) from exc
    return {
        "message": "Market refresh started",
        "market": req.market or "ALL",
        "refresh_id": record.refresh_id,
    }


@router.get("/progress")
@router.get("/refresh")
def get_progress():
    """查看当前更新进度"""
    from services.market_data.refresh_state import RefreshStateStore

    store = RefreshStateStore()
    active = store.get_active()
    return {
        "active": active.to_dict() if active else None,
        "recent": [record.to_dict() for record in store.get_recent()],
    }


@router.post("/adjust-factor")
def trigger_adjust_factor(req: UpdateRequest = UpdateRequest()):
    """手动触发复权因子更新"""
    from services.market_data.updaters.market_updater import update_adjust_factors

    markets = [req.market] if req.market else None
    thread = threading.Thread(
        target=update_adjust_factors, args=(markets,), daemon=True
    )
    thread.start()
    return {
        "message": "Adjust factor update started",
        "markets": markets or ["A", "HK", "US"],
    }
