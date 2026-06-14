"""港股通成分股 API — 查询当前快照 + 手动刷新。

⚠️ 数据是当前快照,无 point-in-time 历史。回测使用接受 ~2-3% look-ahead 偏差。
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/market/hk-connect", tags=["hk-connect"])
logger = logging.getLogger(__name__)

_refresh_lock = threading.Lock()
_refresh_running = False


class RefreshRequest(BaseModel):
    board_code: str = "DLMK0146"  # DLMK0146=全集 / DLMK0144=沪 / DLMK0145=深独有


@router.get("")
def list_hk_connect(board_code: str | None = None):
    """返回最新快照的港股通成分股 code 列表。"""
    from services.market_data.updaters.hk_connect_updater import _parquet_path, get_latest_hk_connect_codes

    codes = sorted(get_latest_hk_connect_codes(board_code=board_code))
    path = _parquet_path()
    as_of = None
    if path.exists():
        try:
            import pandas as pd

            df = pd.read_parquet(path)
            if board_code:
                df = df[df["board"] == board_code]
            if len(df):
                as_of = str(df["as_of_date"].max())
        except Exception as e:
            logger.warning("list_hk_connect: 读快照日期失败: %s", e)

    return {
        "count": len(codes),
        "as_of_date": as_of,
        "board_code": board_code or "ALL",
        "codes": codes,
    }


def _do_refresh(board_code: str) -> None:
    global _refresh_running
    try:
        from services.market_data.updaters.hk_connect_updater import fetch_and_save_hk_connect

        result = fetch_and_save_hk_connect(board_code=board_code)
        logger.info("hk_connect refresh done: %s", result)
    except Exception as e:
        logger.error("hk_connect refresh failed: %s", e)
    finally:
        with _refresh_lock:
            _refresh_running = False


@router.post("/refresh")
def refresh_hk_connect(req: RefreshRequest = RefreshRequest()):
    """后台线程触发拉取 EastMoney 港股通名单。"""
    global _refresh_running
    with _refresh_lock:
        if _refresh_running:
            raise HTTPException(status_code=409, detail="Refresh already in progress")
        _refresh_running = True

    threading.Thread(target=_do_refresh, args=(req.board_code,), daemon=True).start()
    return {"message": "Refresh started", "board_code": req.board_code}
