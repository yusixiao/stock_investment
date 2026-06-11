"""长周期成长 utils:多年年报历史(NOTICE_DATE-aware,严防 look-ahead)。

用例:
- 3 年净利 CAGR(替代 1 年 YOY,过滤短期噪声)
- 连续 N 年 ROE 持续 ≥ 阈值(质量持续性)
- 营收复合增速

只取年报(REPORT_DATE 月=12),按 NOTICE_DATE asof 查询,只回看 ctx.current_date 之前已披露的年报。
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np
import pandas as pd

# {market: {code: DataFrame[NOTICE_DATE, REPORT_DATE, ROEJQ, PARENTNETPROFIT, TOTALOPERATEREVE]}}
_ANNUAL_HIST: dict[str, dict[str, pd.DataFrame]] = {}
_ANNUAL_LOCK = threading.Lock()

_ANNUAL_FIELDS = ["ROEJQ", "PARENTNETPROFIT", "TOTALOPERATEREVE"]


def _build(market: str = "A") -> dict[str, pd.DataFrame]:
    from services.duckdb_store import get_store

    if market.upper() != "A":
        return {}

    store = get_store()
    fields_sql = ", ".join(_ANNUAL_FIELDS)
    sql = f"""
        SELECT _symbol AS code, NOTICE_DATE, REPORT_DATE, {fields_sql}
        FROM v_a_indicator
        WHERE NOTICE_DATE IS NOT NULL
          AND substr(REPORT_DATE, 6, 2) = '12'
        ORDER BY code, NOTICE_DATE, REPORT_DATE
    """
    df = store._conn.execute(sql).fetchdf()
    if df.empty:
        return {}
    df["NOTICE_DATE"] = df["NOTICE_DATE"].astype(str)
    df["REPORT_DATE"] = df["REPORT_DATE"].astype(str)
    df = df.drop_duplicates(["code", "NOTICE_DATE"], keep="last")
    out: dict[str, pd.DataFrame] = {}
    for code, sub in df.groupby("code"):
        out[code] = sub.sort_values("NOTICE_DATE").reset_index(drop=True)
    return out


def _get(market: str = "A") -> dict[str, pd.DataFrame]:
    mk = (market or "A").upper()
    if mk == "HK_CONNECT":
        mk = "HK"
    if mk in _ANNUAL_HIST:
        return _ANNUAL_HIST[mk]
    with _ANNUAL_LOCK:
        if mk not in _ANNUAL_HIST:
            _ANNUAL_HIST[mk] = _build(mk)
    return _ANNUAL_HIST[mk]


def reset_annual_cache() -> None:
    global _ANNUAL_HIST
    with _ANNUAL_LOCK:
        _ANNUAL_HIST = {}


def get_annual_history(ctx, symbol: str, n_years: int) -> Optional[pd.DataFrame]:
    """返回最近 n 年的年报记录(NOTICE_DATE <= ctx.current_date)。

    返回 DataFrame,行数可能 < n_years(如新上市)。无数据返回 None。
    """
    cur_date = getattr(ctx, "current_date", None)
    if cur_date is None:
        return None
    market = getattr(ctx, "market", None) or "A"
    lookup = _get(market)
    g = lookup.get(symbol)
    if g is None or g.empty:
        return None
    idx = int(np.searchsorted(g["NOTICE_DATE"].values, cur_date, side="right"))
    if idx < n_years:
        # 历史不足 n 年
        return None
    return g.iloc[idx - n_years : idx].reset_index(drop=True)


def get_net_profit_cagr(ctx, symbol: str, years: int = 3) -> Optional[float]:
    """计算 years 年净利润 CAGR(单位:小数,如 0.25 = 25%)。

    需要至少 years+1 个年报点(years 年的复合需要 years+1 个数据点)。
    任一端点 ≤0 或缺失返回 None。
    """
    hist = get_annual_history(ctx, symbol, n_years=years + 1)
    if hist is None or len(hist) < years + 1:
        return None
    start = hist.iloc[0]["PARENTNETPROFIT"]
    end = hist.iloc[-1]["PARENTNETPROFIT"]
    if pd.isna(start) or pd.isna(end) or start <= 0 or end <= 0:
        return None
    return float((end / start) ** (1.0 / years) - 1.0)


def all_roe_above(ctx, symbol: str, threshold: float, years: int = 3) -> bool:
    """检查最近 years 个年报 ROE 是否全部 ≥ threshold(%)。

    数据不足或任一年缺失/低于阈值返回 False。
    """
    hist = get_annual_history(ctx, symbol, n_years=years)
    if hist is None or len(hist) < years:
        return False
    for v in hist["ROEJQ"].values:
        if pd.isna(v) or float(v) < threshold:
            return False
    return True


def get_recent_net_profit_yoy(ctx, symbol: str, n: int = 2) -> Optional[list[float]]:
    """返回最近 n 期年报净利润 YoY 序列(单位:%,最新在前)。

    需要至少 n+1 个年报点。任一端点缺失或前一期 <=0 返回 None。
    """
    hist = get_annual_history(ctx, symbol, n_years=n + 1)
    if hist is None or len(hist) < n + 1:
        return None
    np_vals = hist["PARENTNETPROFIT"].values
    out: list[float] = []
    # hist 升序;最近 n 期 = 末尾 n 行,与各自前一年比
    for i in range(len(np_vals) - 1, len(np_vals) - 1 - n, -1):
        cur = np_vals[i]
        prev = np_vals[i - 1]
        if pd.isna(cur) or pd.isna(prev) or prev <= 0:
            return None
        out.append(float((cur / prev - 1.0) * 100.0))
    return out  # [最新, 上一年]


def avg_roe(ctx, symbol: str, years: int = 3) -> Optional[float]:
    """近 years 年平均 ROE(%)。任一年缺失返回 None。"""
    hist = get_annual_history(ctx, symbol, n_years=years)
    if hist is None or len(hist) < years:
        return None
    vals = hist["ROEJQ"].values
    if pd.isna(vals).any():
        return None
    return float(np.mean(vals))
