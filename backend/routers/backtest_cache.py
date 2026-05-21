"""全市场回测数据缓存 API。

- POST /api/backtest/cache/load  body={market}  触发后台加载
- GET  /api/backtest/cache/status              返回三市场状态
- DELETE /api/backtest/cache/{market}          失效缓存
"""

from fastapi import APIRouter, Body, HTTPException

from services.backtest import data_cache


router = APIRouter(prefix="/api/backtest/cache", tags=["backtest-cache"])


@router.get("/status")
def api_cache_status():
    return data_cache.get_status_all()


@router.post("/load")
def api_cache_load(body: dict = Body(...)):
    market = (body.get("market") or "").upper()
    if market not in data_cache.SUPPORTED_MARKETS:
        raise HTTPException(
            status_code=400,
            detail=f"market 必须是 {data_cache.SUPPORTED_MARKETS} 之一",
        )
    return data_cache.load_market_async(market)


@router.delete("/{market}")
def api_cache_invalidate(market: str):
    market = market.upper()
    if market not in data_cache.SUPPORTED_MARKETS:
        raise HTTPException(status_code=400, detail="不支持的 market")
    data_cache.invalidate(market)
    return {"ok": True, "market": market}
