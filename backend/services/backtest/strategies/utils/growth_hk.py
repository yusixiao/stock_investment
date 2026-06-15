"""港股(HK)基本面 as-of utils —— 发布滞后(publication lag)防 look-ahead。

🚨 背景:HK 财务表(v_hk_income / v_hk_indicator)**没有 NOTICE_DATE**,只有
REPORT_DATE。若直接用 REPORT_DATE <= current_date 作可见性判定,会引入严重
look-ahead bias(财报实际披露日远晚于报告期末)。

港交所主板规则:
- 年报(REPORT_DATE 以 -12-31 结尾)正式刊发不晚于报告期末后 4 个月 → 滞后 120 天
- 中报(-06-30)不晚于 3 个月 → 滞后 90 天
- 其余季末(-03-31/-09-30,HK 少见)→ 滞后 90 天

实现:一次性从 DuckDB 拉 v_hk_income + v_hk_indicator(join on REPORT_DATE),
为每行算 available_date = REPORT_DATE + lag,按 (code, available_date) 升序建索引,
二分 as-of 查找,只回看 available_date <= current_date 的报告。

⚠️ 不依赖 ctx.market(回测 Context 里 market 可能为 None)。市场固定 HK。
⚠️ 已知偏差:数据仅含当前在市的 2734 只港股,**退市股缺失 → survivorship bias**。
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

_ANNUAL_LAG_DAYS = 120
_INTERIM_LAG_DAYS = 90

# code -> DataFrame(按 available_date 升序;含年报+中报)
_HK_LOOKUP: dict[str, pd.DataFrame] = {}
# code -> DataFrame(仅年报,按 available_date 升序)
_HK_ANNUAL: dict[str, pd.DataFrame] = {}
_LOCK = threading.Lock()
_LOADED = False

# 拉取字段(income + indicator)
_INCOME_FIELDS = ["PARENT_NETPROFIT", "OPERATE_INCOME", "GROSS_PROFIT", "BASIC_EPS"]
_INDICATOR_FIELDS = [
    "ROEJQ",
    "XSMLL",  # 销售毛利率
    "XSJLL",  # 销售净利率
    "ZCFZL",  # 资产负债率
    "ROA",
    "OPERATE_INCOME_YOY",
    "PARENT_NETPROFIT_YOY",
    "GROSS_PROFIT_YOY",
]


def _available_date(report_date: str) -> str:
    """REPORT_DATE(YYYY-MM-DD)→ 加发布滞后后的可见日(字符串)。"""
    try:
        d = date.fromisoformat(report_date[:10])
    except (ValueError, TypeError):
        return report_date
    lag = _ANNUAL_LAG_DAYS if d.month == 12 else _INTERIM_LAG_DAYS
    return (d + timedelta(days=lag)).isoformat()


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        from services.market_data.duckdb_store import get_store

        store = get_store()
        inc_sql = ", ".join([f"i.{f} AS {f}" for f in _INCOME_FIELDS])
        ind_sql = ", ".join([f"d.{f} AS {f}" for f in _INDICATOR_FIELDS])
        sql = f"""
            SELECT i._symbol AS code,
                   i.REPORT_DATE AS REPORT_DATE,
                   {inc_sql},
                   {ind_sql}
            FROM v_hk_income i
            LEFT JOIN v_hk_indicator d
              ON i._symbol = d._symbol AND i.REPORT_DATE = d.REPORT_DATE
            WHERE i.REPORT_DATE IS NOT NULL
            ORDER BY code, REPORT_DATE
        """
        df = store._conn.execute(sql).fetchdf()
        if df.empty:
            _LOADED = True
            return
        df["REPORT_DATE"] = df["REPORT_DATE"].astype(str)
        df = df.drop_duplicates(["code", "REPORT_DATE"], keep="last")
        df["available_date"] = df["REPORT_DATE"].map(_available_date)
        df["is_annual"] = df["REPORT_DATE"].str.endswith("-12-31")

        for code, sub in df.groupby("code"):
            sub = sub.sort_values("available_date").reset_index(drop=True)
            _HK_LOOKUP[code] = sub
            ann = sub[sub["is_annual"]].reset_index(drop=True)
            if not ann.empty:
                _HK_ANNUAL[code] = ann
        _LOADED = True


def reset_cache() -> None:
    """测试 / 数据更新后重置。"""
    global _HK_LOOKUP, _HK_ANNUAL, _LOADED
    with _LOCK:
        _HK_LOOKUP = {}
        _HK_ANNUAL = {}
        _LOADED = False


def _asof_row(table: pd.DataFrame, current_date: str) -> Optional[pd.Series]:
    if table is None or table.empty:
        return None
    arr = table["available_date"].values
    idx = int(np.searchsorted(arr, current_date, side="right")) - 1
    if idx < 0:
        return None
    return table.iloc[idx]


def get_asof(symbol: str, current_date: str) -> Optional[dict]:
    """返回 available_date <= current_date 的最新一行(年报或中报均可)。

    含 ROE / 毛利率 / 各项 YoY 等;单字段可能为 None。无任何已披露报告返回 None。
    """
    if not current_date:
        return None
    _load()
    row = _asof_row(_HK_LOOKUP.get(symbol), current_date)
    if row is None:
        return None
    out: dict = {"REPORT_DATE": row["REPORT_DATE"], "available_date": row["available_date"]}
    for f in _INCOME_FIELDS + _INDICATOR_FIELDS:
        v = row[f]
        out[f] = None if pd.isna(v) else float(v)
    return out


def get_annual_asof(symbol: str, current_date: str, n: int) -> Optional[pd.DataFrame]:
    """返回最近 n 份**已披露年报**(available_date <= current_date),不足返回 None。"""
    if not current_date:
        return None
    _load()
    table = _HK_ANNUAL.get(symbol)
    if table is None or table.empty:
        return None
    arr = table["available_date"].values
    idx = int(np.searchsorted(arr, current_date, side="right"))
    if idx < n:
        return None
    return table.iloc[idx - n : idx].reset_index(drop=True)


def net_profit_cagr(symbol: str, current_date: str, years: int = 3) -> Optional[float]:
    """归母净利润 years 年 CAGR(小数,如 0.2 = 20%)。需 years+1 个年报点。

    任一端点 <=0 或缺失返回 None。
    """
    hist = get_annual_asof(symbol, current_date, n=years + 1)
    if hist is None or len(hist) < years + 1:
        return None
    start = hist.iloc[0]["PARENT_NETPROFIT"]
    end = hist.iloc[-1]["PARENT_NETPROFIT"]
    if pd.isna(start) or pd.isna(end) or start <= 0 or end <= 0:
        return None
    return float((end / start) ** (1.0 / years) - 1.0)


def revenue_cagr(symbol: str, current_date: str, years: int = 3) -> Optional[float]:
    """营业收入 years 年 CAGR(小数)。"""
    hist = get_annual_asof(symbol, current_date, n=years + 1)
    if hist is None or len(hist) < years + 1:
        return None
    start = hist.iloc[0]["OPERATE_INCOME"]
    end = hist.iloc[-1]["OPERATE_INCOME"]
    if pd.isna(start) or pd.isna(end) or start <= 0 or end <= 0:
        return None
    return float((end / start) ** (1.0 / years) - 1.0)


def recent_np_yoy(symbol: str, current_date: str, n: int = 2) -> Optional[list[float]]:
    """最近 n 期年报净利润 YoY(%,最新在前)。需 n+1 个年报点。"""
    hist = get_annual_asof(symbol, current_date, n=n + 1)
    if hist is None or len(hist) < n + 1:
        return None
    vals = hist["PARENT_NETPROFIT"].values
    out: list[float] = []
    for i in range(len(vals) - 1, len(vals) - 1 - n, -1):
        cur, prev = vals[i], vals[i - 1]
        if pd.isna(cur) or pd.isna(prev) or prev <= 0:
            return None
        out.append(float((cur / prev - 1.0) * 100.0))
    return out


def annual_roe(symbol: str, current_date: str) -> Optional[float]:
    """最新已披露年报 ROE(%)。中报不计入(避免半年 ROE 与年度阈值混用)。"""
    hist = get_annual_asof(symbol, current_date, n=1)
    if hist is None or hist.empty:
        return None
    v = hist.iloc[-1]["ROEJQ"]
    return None if pd.isna(v) else float(v)


def all_annual_roe_above(
    symbol: str, current_date: str, threshold: float, years: int = 3
) -> bool:
    """最近 years 份年报 ROE 是否全部 >= threshold(%)。"""
    hist = get_annual_asof(symbol, current_date, n=years)
    if hist is None or len(hist) < years:
        return False
    for v in hist["ROEJQ"].values:
        if pd.isna(v) or float(v) < threshold:
            return False
    return True
