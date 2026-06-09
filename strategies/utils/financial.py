"""财务三表 + 指标相关 utils 函数(单数据源:financial)。

迁移自 strategies/examples/roe_screener.py(2026-05-18 重构)。
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np
import pandas as pd


def _get_field(ctx, symbol: str, field: str):
    fin = ctx.get_financial(symbol)
    if fin is None:
        return None
    return fin.get(field)


def _get_field_annual(ctx, symbol: str, field: str):
    """从年报(REPORT_DATE = -12-31)取字段。年中查询会回退到上一年报,
    避免季报累计值(如 ROEJQ Q1 = 全年 1/4)误用为年化指标。"""
    if not hasattr(ctx, "get_financial_annual"):
        # 兼容旧 ScreenContext;退化到 get_financial
        return _get_field(ctx, symbol, field)
    fin = ctx.get_financial_annual(symbol)
    if fin is None:
        return None
    return fin.get(field)


def get_roe(ctx, symbol: str) -> float | None:
    """年化 ROE(%)。English schema:ROEJQ(EastMoney indicator),仅取年报口径。

    银行股等季报累计 ROE 不年化(Q1 = 2%、H1 = 4.5%、年报 = 9%),若直接走最近
    报告期会被「假低」筛掉。这里强制走年报。
    """
    return _get_field_annual(ctx, symbol, "ROEJQ")


def get_eps(ctx, symbol: str) -> float | None:
    """基本每股收益。English schema:EPSJB。"""
    return _get_field(ctx, symbol, "EPSJB")


def get_net_profit_growth(ctx, symbol: str) -> float | None:
    """归母净利润同比增长率(%)。English schema:PARENTNETPROFITTZ(EastMoney 累计同比)。"""
    return _get_field(ctx, symbol, "PARENTNETPROFITTZ")


# ===== NOTICE_DATE-aware ROE 查询(2026-06-09 新增) =====
#
# 背景:ctx.get_financial 用 REPORT_DATE <= date 取最新报告期,会把
# REPORT_DATE=2024-03-31 但 NOTICE_DATE=2024-04-28 的 Q1 报告在 4-15 选股时
# 误用 → ~30-60 天 look-ahead bias。
#
# 本工具直接查 v_a_indicator,按 NOTICE_DATE <= ctx.current_date 取最新一份;
# 同 NOTICE_DATE 多条(IPO 招股书 / 重述报告)取最大 REPORT_DATE 作 tiebreak,
# 保证查询确定性。
#
# 实现:模块级 lazy cache(只在第一次调用时拉全 v_a_indicator,~几十万行)。
# 调用方需保证 init_duckdb() 已执行(回测引擎启动时已 init)。

_ROE_NOTICE_LOOKUP: Optional[dict[str, pd.DataFrame]] = None
_ROE_NOTICE_LOCK = threading.Lock()


def _build_roe_notice_lookup() -> dict[str, pd.DataFrame]:
    """一次性从 DuckDB 拉 v_a_indicator,按 (code, NOTICE_DATE) 去重 + 排序。

    去重铁律:同 (code, NOTICE_DATE) 取 max(REPORT_DATE),保证查询确定性。
    """
    # 延迟 import,避免污染 utils 模块顶层依赖
    from services.duckdb_store import get_store

    store = get_store()
    sql = """
        SELECT _symbol AS code,
               NOTICE_DATE,
               REPORT_DATE,
               ROEJQ
        FROM v_a_indicator
        WHERE NOTICE_DATE IS NOT NULL
          AND ROEJQ IS NOT NULL
        ORDER BY code, NOTICE_DATE
    """
    df = store._conn.execute(sql).fetchdf()
    df["NOTICE_DATE"] = df["NOTICE_DATE"].astype(str)
    df["REPORT_DATE"] = df["REPORT_DATE"].astype(str)
    # tied NOTICE_DATE 取最大 REPORT_DATE
    df = df.sort_values(["code", "NOTICE_DATE", "REPORT_DATE"]).drop_duplicates(
        ["code", "NOTICE_DATE"], keep="last"
    )
    out: dict[str, pd.DataFrame] = {}
    for code, sub in df.groupby("code"):
        out[code] = sub.sort_values("NOTICE_DATE").reset_index(drop=True)
    return out


def _get_roe_notice_lookup() -> dict[str, pd.DataFrame]:
    """线程安全 lazy 构建。"""
    global _ROE_NOTICE_LOOKUP
    if _ROE_NOTICE_LOOKUP is not None:
        return _ROE_NOTICE_LOOKUP
    with _ROE_NOTICE_LOCK:
        if _ROE_NOTICE_LOOKUP is None:
            _ROE_NOTICE_LOOKUP = _build_roe_notice_lookup()
    return _ROE_NOTICE_LOOKUP


def reset_roe_notice_cache() -> None:
    """测试 / 数据更新后重置 cache。"""
    global _ROE_NOTICE_LOOKUP
    with _ROE_NOTICE_LOCK:
        _ROE_NOTICE_LOOKUP = None


def get_roe_as_of_notice(ctx, symbol: str) -> Optional[float]:
    """返回 NOTICE_DATE <= ctx.current_date 的最新已披露 ROEJQ(%)。

    与 get_roe(年报口径)的差异:
    - 取季度 ROEJQ(可能是 Q1/H1/Q3/年报),不限定 -12-31
    - 用 NOTICE_DATE 防 look-ahead,而非 REPORT_DATE

    A 股专用(只查 v_a_indicator)。HK/US 不支持,返回 None。
    """
    cur_date = getattr(ctx, "current_date", None)
    if cur_date is None:
        return None
    lookup = _get_roe_notice_lookup()
    g = lookup.get(symbol)
    if g is None or g.empty:
        return None
    idx = int(np.searchsorted(g["NOTICE_DATE"].values, cur_date, side="right")) - 1
    if idx < 0:
        return None
    val = g.iloc[idx]["ROEJQ"]
    if pd.isna(val):
        return None
    return float(val)


def filter_by_roe_as_of_notice(
    ctx, symbols: list[str], *, min_roe: float = 5.0
) -> list[str]:
    """按 NOTICE_DATE-aware ROEJQ 筛选,严防 look-ahead。

    与 filter_by_roe(年报口径)的差异见 get_roe_as_of_notice docstring。
    stage = "financial.roe_notice"
    """
    stage = "financial.roe_notice"
    result: list[str] = []
    for sym in symbols:
        roe = get_roe_as_of_notice(ctx, sym)
        if roe is None:
            ctx.log_reject(sym, stage, "no_data", threshold=min_roe)
            continue
        ctx.record_factor(sym, "ROE", roe)
        if roe >= min_roe:
            ctx.log_pass(sym, stage, roe=roe, threshold=min_roe)
            result.append(sym)
        else:
            ctx.log_reject(sym, stage, "below_threshold", roe=roe, threshold=min_roe)
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result


def filter_by_roe(ctx, symbols: list[str], *, min_roe: float = 10.0) -> list[str]:
    """筛选 ROE >= min_roe 的股票。

    stage = "financial.roe"
    """
    stage = "financial.roe"
    result: list[str] = []
    for sym in symbols:
        roe = get_roe(ctx, sym)
        if roe is None:
            ctx.log_reject(sym, stage, "no_data", threshold=min_roe)
            continue
        # 因子收集 — 策略雷达展示 ROE 实际值
        ctx.record_factor(sym, "ROE", roe)
        if roe >= min_roe:
            ctx.log_pass(sym, stage, roe=roe, threshold=min_roe)
            result.append(sym)
        else:
            ctx.log_reject(sym, stage, "below_threshold", roe=roe, threshold=min_roe)
    ctx.log_flow(stage, input=len(symbols), passed=len(result))
    return result
