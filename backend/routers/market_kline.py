"""多市场 K-line API — DuckDB 查询层 + 复权 + 周期聚合"""

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import ORJSONResponse
from typing import Optional

import pandas as pd

from services.duckdb_store import get_store
from services.indicator import calc_macd

router = APIRouter(prefix="/api/market", tags=["market-kline"])


def _resolve_market(code: str) -> str:
    if code.endswith(".SH") or code.endswith(".SZ"):
        return "A"
    elif code.endswith(".HK"):
        return "HK"
    else:
        return "US"


def _apply_adjust(
    df: pd.DataFrame, code: str, market: str, adjust: str
) -> pd.DataFrame:
    """应用复权因子到 OHLC 价格"""
    store = get_store()
    view = f"v_{market.lower()}_adjust_factor"

    try:
        adj_df = store.query(
            f"SELECT dividOperateDate, foreAdjustFactor, backAdjustFactor "
            f"FROM {view} WHERE _symbol = ? ORDER BY dividOperateDate",
            [code],
        )
    except Exception:
        return df

    if adj_df.empty:
        return df

    adj_df = adj_df.rename(columns={"dividOperateDate": "adj_date"})
    adj_df["adj_date"] = pd.to_datetime(adj_df["adj_date"])
    df["_date_dt"] = pd.to_datetime(df["date"])

    # ASOF merge: 每日K线匹配最近的(<=该日期)复权因子
    df = df.sort_values("_date_dt")
    adj_df = adj_df.sort_values("adj_date")
    df = pd.merge_asof(
        df, adj_df, left_on="_date_dt", right_on="adj_date", direction="forward"
    )

    price_cols = ["open", "high", "low", "close", "preclose"]

    if adjust == "qfq":
        latest_factor = adj_df["foreAdjustFactor"].iloc[-1]
        if latest_factor and latest_factor != 0:
            factor = df["foreAdjustFactor"].fillna(latest_factor) / latest_factor
            for col in price_cols:
                df[col] = df[col] * factor
    elif adjust == "hfq":
        earliest_factor = adj_df["backAdjustFactor"].iloc[0]
        if earliest_factor and earliest_factor != 0:
            factor = df["backAdjustFactor"].fillna(earliest_factor) / earliest_factor
            for col in price_cols:
                df[col] = df[col] * factor

    df = df.drop(
        columns=["_date_dt", "adj_date", "foreAdjustFactor", "backAdjustFactor"],
        errors="ignore",
    )
    # 复权后重新计算涨跌幅
    if "preclose" in df.columns and "close" in df.columns:
        df["pctChg"] = ((df["close"] - df["preclose"]) / df["preclose"] * 100).round(4)
    return df


def _aggregate_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """将日线聚合为周线/月线"""
    df["_date_dt"] = pd.to_datetime(df["date"])
    df = df.set_index("_date_dt")

    freq = "W-FRI" if period == "weekly" else "ME"
    agg_dict: dict = {
        "date": "last",
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    if "preclose" in df.columns:
        agg_dict["preclose"] = "first"
    if "amount" in df.columns:
        agg_dict["amount"] = "sum"
    if "turn" in df.columns:
        agg_dict["turn"] = "sum"

    agg = df.resample(freq).agg(agg_dict).dropna(subset=["date"])
    result = agg.reset_index(drop=True)

    # 重新计算涨跌幅
    if "preclose" in result.columns:
        result["pctChg"] = (
            (result["close"] - result["preclose"]) / result["preclose"] * 100
        ).round(4)
    return result


@router.get("/{code}/kline")
def get_market_kline(
    code: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: Optional[int] = Query(
        None, ge=1, le=20000, description="最多返回条数，不传则返回全部"
    ),
    period: str = Query("daily", description="daily/weekly/monthly"),
    adjust: str = Query("raw", description="raw/qfq/hfq"),
):
    market = _resolve_market(code)
    store = get_store()

    df = store.query_kline(market, code, start_date=start_date, end_date=end_date)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"Stock {code} not found")

    # 只保留需要的列
    cols = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turn",
        "pctChg",
    ]
    df = df[[c for c in cols if c in df.columns]]

    # 复权
    if adjust != "raw":
        df = _apply_adjust(df, code, market, adjust)

    # 周期聚合
    if period in ("weekly", "monthly"):
        df = _aggregate_period(df, period)

    # 排序并截断
    df = df.sort_values("date", ascending=True)
    if limit:
        df = df.tail(limit)

    # 四舍五入价格
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df[col] = df[col].round(4)

    # 计算 MACD
    macd_df = calc_macd(df)
    macd_records = (
        macd_df[["date", "dif", "dea", "macd"]].round(4).to_dict(orient="records")
    )

    # 计算成交量 MA5/MA10
    df = df.sort_values("date")
    df["vol_ma5"] = df["volume"].rolling(5).mean().round(0)
    df["vol_ma10"] = df["volume"].rolling(10).mean().round(0)
    vol_ma_records = df[["date", "vol_ma5", "vol_ma10"]].to_dict(orient="records")

    records = df.drop(columns=["vol_ma5", "vol_ma10"]).to_dict(orient="records")
    return ORJSONResponse(
        content={
            "code": code,
            "period": period,
            "adjust": adjust,
            "data": records,
            "macd": macd_records,
            "vol_ma": vol_ma_records,
        }
    )
