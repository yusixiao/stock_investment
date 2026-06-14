"""股票搜索 API — 前缀自动补全"""

from fastapi import APIRouter, Query

from services.market_data.stock_index import search_stocks

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def stock_search(
    q: str = Query("", description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50, description="最大返回数量"),
):
    results = search_stocks(q, limit=limit)
    return {"results": results}
