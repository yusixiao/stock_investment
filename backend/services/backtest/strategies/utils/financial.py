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


# ===== NOTICE_DATE-aware ROE 查询(2026-06-09 新增,2026-06-10 扩展支持 HK)=====
#
# 背景:ctx.get_financial 用 REPORT_DATE <= date 取最新报告期,会把
# REPORT_DATE=2024-03-31 但 NOTICE_DATE=2024-04-28 的 Q1 报告在 4-15 选股时
# 误用 → ~30-60 天 look-ahead bias。
#
# A 股(`v_a_indicator`)有真实 NOTICE_DATE 列,严格防 look-ahead。
# HK 股(`v_hk_indicator`)EastMoney F10 不返回公告日,用 REPORT_DATE + 120 天
# 近似公告日(港交所/中证监年报披露 deadline 都是次年 4-30,12-31 + 120 天 ≈ 4-30,
# 偏保守:回测在 deadline 之后才用上数据,只引入轻微 lag bias,不会 look-ahead)。
# 同 NOTICE_DATE 多条(IPO 招股书 / 重述报告)取最大 REPORT_DATE 作 tiebreak,
# 保证查询确定性。
#
# 实现:模块级 lazy cache,按 market 分桶(A / HK 两份独立 cache)。
# 调用方需保证 init_duckdb() 已执行(回测引擎启动时已 init)。

# {market: {code: DataFrame}};HK_CONNECT 走 HK,US 暂未支持
_ROE_NOTICE_LOOKUP: dict[str, dict[str, pd.DataFrame]] = {}
_ROE_NOTICE_LOCK = threading.Lock()

# 年报-only(REPORT_DATE 月=12)版本,独立 cache
_ROE_NOTICE_ANNUAL_LOOKUP: dict[str, dict[str, pd.DataFrame]] = {}
_ROE_NOTICE_ANNUAL_LOCK = threading.Lock()

# HK 公告日近似:REPORT_DATE + N 天(近似实际披露日)
# 港股年报披露 deadline = financial year end + 4 个月(港交所 ETO 13.46(2));
# 12-31 报告期 deadline 是次年 4-30,即 +120 日。多数公司提前 1-2 个月披露,
# 但回测取 deadline 偏保守,确保不引入 look-ahead bias。
_HK_NOTICE_LAG_DAYS = 120


def _build_roe_notice_lookup(
    market: str = "A", annual_only: bool = False
) -> dict[str, pd.DataFrame]:
    """一次性从 DuckDB 拉 indicator 视图,按 (code, NOTICE_DATE) 去重 + 排序。

    去重铁律:同 (code, NOTICE_DATE) 取 max(REPORT_DATE),保证查询确定性。

    market:
    - "A":查 v_a_indicator,用真实 NOTICE_DATE
    - "HK":查 v_hk_indicator,无 NOTICE_DATE → 用 REPORT_DATE + 120 天近似公告日
    - "HK_CONNECT":等价 HK(同物理数据,见 AGENTS.md)

    annual_only=True 时只保留 REPORT_DATE 月份=12 的年报。
    """
    # 延迟 import,避免污染 utils 模块顶层依赖
    from services.market_data.duckdb_store import get_store

    store = get_store()
    market_norm = market.upper()
    if market_norm == "HK_CONNECT":
        market_norm = "HK"

    if market_norm == "A":
        view = "v_a_indicator"
        date_expr = "NOTICE_DATE"
        where = ["NOTICE_DATE IS NOT NULL", "ROEJQ IS NOT NULL"]
    elif market_norm == "HK":
        view = "v_hk_indicator"
        # HK 无 NOTICE_DATE 列,用 REPORT_DATE + 120 天近似;DuckDB date 加法
        date_expr = (
            f"strftime(strptime(REPORT_DATE, '%Y-%m-%d') + "
            f"INTERVAL {_HK_NOTICE_LAG_DAYS} DAY, '%Y-%m-%d')"
        )
        where = ["REPORT_DATE IS NOT NULL", "ROEJQ IS NOT NULL"]
    else:
        # US 暂未支持,返回空 dict 让上层 fallback 到 None
        return {}

    if annual_only:
        # REPORT_DATE 形如 'YYYY-12-31',直接字符串截取月份
        where.append("substr(REPORT_DATE, 6, 2) = '12'")
    sql = f"""
        SELECT _symbol AS code,
               {date_expr} AS NOTICE_DATE,
               REPORT_DATE,
               ROEJQ
        FROM {view}
        WHERE {" AND ".join(where)}
        ORDER BY code, NOTICE_DATE
    """
    df = store._conn.execute(sql).fetchdf()
    if df.empty:
        return {}
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


def _normalize_market(market: Optional[str]) -> str:
    """统一 market key:HK_CONNECT → HK;空值/未知 → A(默认 A 股)。"""
    if not market:
        return "A"
    m = str(market).upper()
    if m == "HK_CONNECT":
        return "HK"
    if m in {"A", "HK", "US"}:
        return m
    return "A"


def _get_roe_notice_lookup(market: str = "A") -> dict[str, pd.DataFrame]:
    """线程安全 lazy 构建,按 market 分桶 cache。"""
    mk = _normalize_market(market)
    if mk in _ROE_NOTICE_LOOKUP:
        return _ROE_NOTICE_LOOKUP[mk]
    with _ROE_NOTICE_LOCK:
        if mk not in _ROE_NOTICE_LOOKUP:
            _ROE_NOTICE_LOOKUP[mk] = _build_roe_notice_lookup(market=mk)
    return _ROE_NOTICE_LOOKUP[mk]


def reset_roe_notice_cache() -> None:
    """测试 / 数据更新后重置 cache(全部 market + quarterly + annual)。"""
    global _ROE_NOTICE_LOOKUP, _ROE_NOTICE_ANNUAL_LOOKUP
    with _ROE_NOTICE_LOCK:
        _ROE_NOTICE_LOOKUP = {}
    with _ROE_NOTICE_ANNUAL_LOCK:
        _ROE_NOTICE_ANNUAL_LOOKUP = {}


def _get_roe_notice_annual_lookup(market: str = "A") -> dict[str, pd.DataFrame]:
    """线程安全 lazy 构建(年报版),按 market 分桶 cache。"""
    mk = _normalize_market(market)
    if mk in _ROE_NOTICE_ANNUAL_LOOKUP:
        return _ROE_NOTICE_ANNUAL_LOOKUP[mk]
    with _ROE_NOTICE_ANNUAL_LOCK:
        if mk not in _ROE_NOTICE_ANNUAL_LOOKUP:
            _ROE_NOTICE_ANNUAL_LOOKUP[mk] = _build_roe_notice_lookup(
                market=mk, annual_only=True
            )
    return _ROE_NOTICE_ANNUAL_LOOKUP[mk]


def _detect_market_from_symbol(symbol: str) -> str:
    """从 symbol 后缀推断 market:`.SH/.SZ/.BJ` → A;`.HK` → HK;`.US/无后缀` → US。

    用作 fallback,优先使用 ctx.market。
    """
    if not symbol:
        return "A"
    sym = symbol.upper()
    if sym.endswith(".HK"):
        return "HK"
    if sym.endswith((".SH", ".SZ", ".BJ")):
        return "A"
    return "A"  # 默认 A,保持向后兼容


def _resolve_market(ctx, symbol: str) -> str:
    """优先 ctx.market;若无,从 symbol 后缀推断。HK_CONNECT → HK。"""
    mk = getattr(ctx, "market", None)
    if mk:
        return _normalize_market(mk)
    return _detect_market_from_symbol(symbol)


def get_roe_annual_as_of_notice(ctx, symbol: str) -> Optional[float]:
    """返回 NOTICE_DATE <= ctx.current_date 的最近**年报** ROEJQ(%)。

    与 ``get_roe_as_of_notice`` 的差异:只看 REPORT_DATE 月份=12 的年报,
    避免 Q1/H1/Q3 累计同期 ROE 被误用为「年化指标」(累计语义,Q1≈年化÷4)。

    用例:5/9/11 月调仓时,Q1/H1/Q3 累计同期 ROE 阈值难以稳定刻度;直接用上一年完整
    年报的年化 ROE 更稳定。

    Market 路由:优先 ctx.market(回测引擎注入,HK_CONNECT 归一到 HK);
    否则按 symbol 后缀推断(.HK→HK / .SH/.SZ/.BJ→A)。HK 用 REPORT_DATE+120 天
    近似 NOTICE_DATE。US 暂不支持,返回 None。
    """
    cur_date = getattr(ctx, "current_date", None)
    if cur_date is None:
        return None
    market = _resolve_market(ctx, symbol)
    lookup = _get_roe_notice_annual_lookup(market)
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


def filter_by_roe_annual_as_of_notice(
    ctx, symbols: list[str], *, min_roe: float = 5.0
) -> list[str]:
    """按 NOTICE_DATE-aware 年报 ROEJQ 筛选,严防 look-ahead。

    与 ``filter_by_roe_as_of_notice`` 的差异见 ``get_roe_annual_as_of_notice``。
    stage = "financial.roe_annual_notice"
    """
    stage = "financial.roe_annual_notice"
    result: list[str] = []
    for sym in symbols:
        roe = get_roe_annual_as_of_notice(ctx, sym)
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


def get_roe_as_of_notice(ctx, symbol: str) -> Optional[float]:
    """返回 NOTICE_DATE <= ctx.current_date 的最新已披露 ROEJQ(%)。

    与 get_roe(年报口径)的差异:
    - 取季度 ROEJQ(可能是 Q1/H1/Q3/年报),不限定 -12-31
    - 用 NOTICE_DATE 防 look-ahead,而非 REPORT_DATE

    Market 路由同 ``get_roe_annual_as_of_notice``。
    """
    cur_date = getattr(ctx, "current_date", None)
    if cur_date is None:
        return None
    market = _resolve_market(ctx, symbol)
    lookup = _get_roe_notice_lookup(market)
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
