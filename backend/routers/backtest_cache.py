"""全市场回测数据缓存 API。

- POST /api/backtest/cache/load  body={market}  触发后台加载
- GET  /api/backtest/cache/status              返回三市场状态
- DELETE /api/backtest/cache/{market}          失效缓存
"""

from fastapi import APIRouter, Body, HTTPException

from services.backtest import data_cache
from services.backtest.market_filter import resolve_data_market


router = APIRouter(prefix="/api/backtest/cache", tags=["backtest-cache"])


@router.get("/status")
def api_cache_status():
    """返回三个物理市场状态。HK_CONNECT 复用 HK 缓存,前端直接读 status.HK 即可。"""
    return data_cache.get_status_all()


@router.post("/load")
def api_cache_load(body: dict = Body(...)):
    market = (body.get("market") or "").upper()
    # HK_CONNECT 共享 HK 缓存
    market = resolve_data_market(market)
    if market not in data_cache.SUPPORTED_MARKETS:
        raise HTTPException(
            status_code=400,
            detail=f"market 必须是 {data_cache.SUPPORTED_MARKETS} 或 HK_CONNECT",
        )
    return data_cache.load_market_async(market)


@router.delete("/{market}")
def api_cache_invalidate(market: str):
    market = resolve_data_market(market.upper())
    if market not in data_cache.SUPPORTED_MARKETS:
        raise HTTPException(status_code=400, detail="不支持的 market")
    data_cache.invalidate(market)
    return {"ok": True, "market": market}
