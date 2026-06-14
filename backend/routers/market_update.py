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
    from services.market_data.updaters.market_updater import (
        get_update_progress,
        update_all_markets,
        update_single_market,
    )

    progress = get_update_progress()
    if progress["status"] == "running":
        raise HTTPException(status_code=409, detail="Update already in progress")

    if req.market:
        if req.market not in ("A", "HK", "US"):
            raise HTTPException(status_code=400, detail=f"Invalid market: {req.market}")
        thread = threading.Thread(
            target=update_single_market, args=(req.market,), daemon=True
        )
    else:
        thread = threading.Thread(
            target=update_all_markets, kwargs={"parallel": True}, daemon=True
        )

    thread.start()
    return {"message": "Update started", "market": req.market or "ALL"}


@router.get("/progress")
def get_progress():
    """查看当前更新进度"""
    from services.market_data.updaters.market_updater import get_update_progress

    return get_update_progress()


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
