import json

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
from pathlib import Path
from typing import Optional

from config import RAW_KLINE_DIR
from services.stock_data import list_stocks, get_kline, aggregate_kline
from services.indicator import calc_ma, calc_macd, calc_kdj, calc_boll
from services.qfq_cache import get_qfq_kline
from services.api_utils import safe_json

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("")
def api_list_stocks(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    all_stocks = list_stocks(search=search)
    total = len(all_stocks)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "stocks": all_stocks[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{symbol}/kline")
def api_get_kline(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    period: str = Query("daily", description="daily/weekly/monthly"),
    adjust: str = Query("raw", description="raw/qfq"),
):
    if adjust == "qfq":
        df = get_qfq_kline(symbol, start_date=start_date, end_date=end_date)
        if df.empty:
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
    else:
        filepath = RAW_KLINE_DIR / f"{symbol}.parquet"
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
        df = get_kline(filepath, start_date=start_date, end_date=end_date)
    if period in ("weekly", "monthly"):
        df = aggregate_kline(df, period=period)
    return df.to_dict(orient="records")


@router.get("/{symbol}/indicators")
def api_get_indicators(
    symbol: str,
    types: str = Query("ma", description="Comma-separated: ma,macd,kdj,boll"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    period: str = Query("daily", description="daily/weekly/monthly"),
    adjust: str = Query("raw", description="raw/qfq"),
):
    if adjust == "qfq":
        df = get_qfq_kline(symbol, start_date=start_date, end_date=end_date)
        if df.empty:
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
    else:
        filepath = RAW_KLINE_DIR / f"{symbol}.parquet"
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
        df = get_kline(filepath, start_date=start_date, end_date=end_date)
    if period in ("weekly", "monthly"):
        df = aggregate_kline(df, period=period)

    indicator_types = [t.strip() for t in types.split(",")]
    result = {}

    if "ma" in indicator_types:
        ma_df = calc_ma(df)
        result["ma"] = ma_df[["date", "ma5", "ma10", "ma20", "ma60"]].to_dict(
            orient="records"
        )

    if "macd" in indicator_types:
        macd_df = calc_macd(df)
        result["macd"] = macd_df[["date", "dif", "dea", "macd"]].to_dict(
            orient="records"
        )

    if "kdj" in indicator_types:
        kdj_df = calc_kdj(df)
        result["kdj"] = kdj_df[["date", "k", "d", "j"]].to_dict(orient="records")

    if "boll" in indicator_types:
        boll_df = calc_boll(df)
        result["boll"] = boll_df[
            ["date", "boll_upper", "boll_mid", "boll_lower"]
        ].to_dict(orient="records")

    return Response(
        content=json.dumps(safe_json(result), ensure_ascii=False),
        media_type="application/json",
    )
