import json

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
from typing import Optional

from services.market_data.stock_data import aggregate_kline
from services.market_data.indicator import calc_ma, calc_macd, calc_kdj, calc_boll
from services.market_data.duckdb_store import get_store
from services.api_utils import safe_json

_KLINE_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


def _load_kline(symbol: str, adjust: str, start_date, end_date):
    """统一从 DuckDB 取 K 线(raw / qfq),返回 7 列升序 DataFrame。"""
    store = get_store()
    if adjust == "qfq":
        df = store.query_qfq_kline("A", symbol, start_date, end_date)
    else:
        df = store.query_kline("A", symbol, start_date=start_date, end_date=end_date)
        # query_kline 返回视图全部列(含 _symbol/filename),裁剪到标准 7 列
        df = df[[c for c in _KLINE_COLS if c in df.columns]]
    if df.empty:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
    return df


router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("")
def api_list_stocks(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """A 股清单 + 最新 K 线汇总。从 DuckDB 一条 SQL 取每只股票最新 (date, close, volume)。"""
    store = get_store()
    sql = """
        SELECT _symbol AS symbol, date AS latest_date, close, volume
        FROM v_a_daily
        QUALIFY row_number() OVER (PARTITION BY _symbol ORDER BY date DESC) = 1
    """
    df = store.query(sql)
    if search:
        df = df[df["symbol"].str.contains(search, case=False, na=False)]
    df = df.sort_values("symbol").reset_index(drop=True)
    # NaN/Inf 防御:close/volume 转 float 时清洗
    df["close"] = df["close"].fillna(0.0).astype(float)
    df["volume"] = df["volume"].fillna(0.0).astype(float)
    total = len(df)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "stocks": df.iloc[start:end].to_dict(orient="records"),
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
    df = _load_kline(symbol, adjust, start_date, end_date)
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
    df = _load_kline(symbol, adjust, start_date, end_date)
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
