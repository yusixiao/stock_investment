"""成长性因子 utils:NOTICE_DATE-aware,严防 look-ahead。

字段(EastMoney indicator 视图):
- TOTALOPERATEREVETZ: 营业总收入同比增长率(%,TTM 累计同比口径)
- KCFJCXSYJLRTZ: 扣非净利润同比增长率(%)
- PARENTNETPROFITTZ: 归母净利润同比增长率(%)
- ROEJQ: 净资产收益率(%)
- NCO_NETPROFIT: 经营现金流 / 净利润(净现比)

设计:一次性 DuckDB 拉全表 + 按 (code, NOTICE_DATE) 索引,O(log N) as-of 查找。
A 股用真实 NOTICE_DATE,严格防 look-ahead。HK/US 暂未实现(框架预留)。
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np
import pandas as pd

# {market: {code: DataFrame}} — 按 NOTICE_DATE 升序,(code, NOTICE_DATE) 已去重
_GROWTH_LOOKUP: dict[str, dict[str, pd.DataFrame]] = {}
_GROWTH_LOCK = threading.Lock()

_GROWTH_FIELDS = [
    "TOTALOPERATEREVETZ",
    "KCFJCXSYJLRTZ",
    "PARENTNETPROFITTZ",
    "ROEJQ",
    "NCO_NETPROFIT",
]


def _build_growth_lookup(market: str = "A") -> dict[str, pd.DataFrame]:
    """从 v_a_indicator 一次性拉全表 + 5 个成长字段。

    去重铁律:同 (code, NOTICE_DATE) 取 max(REPORT_DATE)。
    HK/US 暂返回空 dict,fallback to None。
    """
    from services.market_data.duckdb_store import get_store

    market_norm = market.upper()
    if market_norm == "HK_CONNECT":
        market_norm = "HK"
    if market_norm != "A":
        # HK/US 暂未实现成长字段查询
        return {}

    store = get_store()
    fields_sql = ", ".join(_GROWTH_FIELDS)
    sql = f"""
        SELECT _symbol AS code,
               NOTICE_DATE,
               REPORT_DATE,
               {fields_sql}
        FROM v_a_indicator
        WHERE NOTICE_DATE IS NOT NULL
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


def _get_growth_lookup(market: str = "A") -> dict[str, pd.DataFrame]:
    mk = (market or "A").upper()
    if mk == "HK_CONNECT":
        mk = "HK"
    if mk in _GROWTH_LOOKUP:
        return _GROWTH_LOOKUP[mk]
    with _GROWTH_LOCK:
        if mk not in _GROWTH_LOOKUP:
            _GROWTH_LOOKUP[mk] = _build_growth_lookup(mk)
    return _GROWTH_LOOKUP[mk]


def reset_growth_cache() -> None:
    """测试 / 数据更新后重置 cache。"""
    global _GROWTH_LOOKUP
    with _GROWTH_LOCK:
        _GROWTH_LOOKUP = {}


def get_growth_metrics_as_of_notice(
    ctx, symbol: str
) -> Optional[dict[str, Optional[float]]]:
    """返回 NOTICE_DATE <= ctx.current_date 的最新一行 5 字段值。

    返回 None 表示无任何已披露报告;返回 dict 时单字段可能为 NaN/None。
    """
    cur_date = getattr(ctx, "current_date", None)
    if cur_date is None:
        return None
    market = getattr(ctx, "market", None) or "A"
    lookup = _get_growth_lookup(market)
    g = lookup.get(symbol)
    if g is None or g.empty:
        return None
    idx = int(np.searchsorted(g["NOTICE_DATE"].values, cur_date, side="right")) - 1
    if idx < 0:
        return None
    row = g.iloc[idx]
    out: dict[str, Optional[float]] = {}
    for f in _GROWTH_FIELDS:
        v = row[f]
        out[f] = None if pd.isna(v) else float(v)
    return out
