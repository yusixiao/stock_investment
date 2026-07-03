"""资产负债表长周期历史 utils:多年年报负债率序列(NOTICE_DATE-aware,严防 look-ahead)。

用途(困境反转型 Turnarounds「去杠杆」信号):
- 判断资产负债率是否**逐年下降**(债务改善 = 林奇困境反转的核心存活性检验:
  "Is the company reducing debt? Is the balance sheet improving?")。

🚨 为什么单独建这个 util,而不用 ctx.get_balance_annual_history:
  MarketData 的 get_balance_annual_history 走 `_lookup_financial_history`,按 **REPORT_DATE**
  as-of 查询(结果键即 REPORT_DATE),存在最多约 4 个月的披露滞后前视窗口
  (REPORT_DATE=2023-12-31 的年报实际 NOTICE_DATE 可能到 2024-04-30 才披露)。
  在**月度调仓**下,1-4 月决策会读到尚未披露的上年年报 → look-ahead bias。
  本 util 与 growth_long 一致,直接从 v_a_balance 读 **NOTICE_DATE** 并严格按
  NOTICE_DATE ≤ ctx.current_date 过滤,消除该前视。

数据通路:
- v_a_balance(EastMoney 资产负债表年报,_symbol 主键)
- 负债率 = TOTAL_LIABILITIES / TOTAL_ASSETS(小数 0~1);缺失时回退 DEBT_ASSET_RATIO/100
  (DEBT_ASSET_RATIO 量纲为百分比 0~100,实测覆盖率 99.9%)。

设计原则(与 quality / growth_long 一致):
1. 只取年报(REPORT_DATE 月 = 12)。
2. 按 NOTICE_DATE ≤ cur 严格 PIT 过滤,再按 REPORT_DATE 去重(保留最新披露的重述版本),
   保证相邻两点是**不同财年**(重述不会污染 YoY 比较)。
3. 数据缺失 / 不足 → 返 None,由调用方决定放行还是淘汰。
"""

from __future__ import annotations

import threading
from typing import Optional

import pandas as pd

# {market: {code: DataFrame[NOTICE_DATE, REPORT_DATE, TOTAL_LIABILITIES, TOTAL_ASSETS,
#           DEBT_ASSET_RATIO, TOTAL_PARENT_EQUITY, GOODWILL, INTANGIBLE_ASSET, MONETARYFUNDS]}}
_BAL_HIST: dict[str, dict[str, pd.DataFrame]] = {}
_BAL_LOCK = threading.Lock()

_BAL_FIELDS = [
    "TOTAL_LIABILITIES", "TOTAL_ASSETS", "DEBT_ASSET_RATIO",
    # 隐蔽资产型(Asset Plays)有形账面折价 / 净现金所需科目(2026-07-02 增补):
    #   有形账面价值 = 归母权益 − 商誉 − 无形资产;净现金 = 货币资金 − 总负债。
    "TOTAL_PARENT_EQUITY", "GOODWILL", "INTANGIBLE_ASSET", "MONETARYFUNDS",
]


def _build(market: str = "A") -> dict[str, pd.DataFrame]:
    from services.market_data.duckdb_store import get_store

    if market.upper() != "A":
        # HK/US 资产负债表 schema 与字段语义不同,暂不支持(与 growth_long 一致仅 A 股)
        return {}

    store = get_store()
    fields_sql = ", ".join(_BAL_FIELDS)
    sql = f"""
        SELECT _symbol AS code, NOTICE_DATE, REPORT_DATE, {fields_sql}
        FROM v_a_balance
        WHERE NOTICE_DATE IS NOT NULL
          AND substr(REPORT_DATE, 6, 2) = '12'
        ORDER BY code, NOTICE_DATE, REPORT_DATE
    """
    df = store._conn.execute(sql).fetchdf()
    if df.empty:
        return {}
    df["NOTICE_DATE"] = df["NOTICE_DATE"].astype(str)
    df["REPORT_DATE"] = df["REPORT_DATE"].astype(str)
    # 同一 (code, NOTICE_DATE) 去重(极少数重复披露),保留最后一条
    df = df.drop_duplicates(["code", "NOTICE_DATE"], keep="last")
    out: dict[str, pd.DataFrame] = {}
    for code, sub in df.groupby("code"):
        out[code] = sub.sort_values("NOTICE_DATE").reset_index(drop=True)
    return out


def _get(market: str = "A") -> dict[str, pd.DataFrame]:
    mk = (market or "A").upper()
    if mk == "HK_CONNECT":
        mk = "HK"
    if mk in _BAL_HIST:
        return _BAL_HIST[mk]
    with _BAL_LOCK:
        if mk not in _BAL_HIST:
            _BAL_HIST[mk] = _build(mk)
    return _BAL_HIST[mk]


def reset_balance_cache() -> None:
    global _BAL_HIST
    with _BAL_LOCK:
        _BAL_HIST = {}


def _row_debt_ratio(row) -> Optional[float]:
    """单行负债率(小数 0~1)。优先 TOTAL_LIABILITIES/TOTAL_ASSETS,回退 DEBT_ASSET_RATIO/100。"""
    liab = row.get("TOTAL_LIABILITIES")
    assets = row.get("TOTAL_ASSETS")
    if (
        liab is not None
        and assets is not None
        and not pd.isna(liab)
        and not pd.isna(assets)
        and float(assets) > 0
    ):
        return float(liab) / float(assets)
    dar = row.get("DEBT_ASSET_RATIO")
    if dar is not None and not pd.isna(dar):
        return float(dar) / 100.0
    return None


def get_debt_ratios(ctx, symbol: str, n_years: int) -> Optional[list[float]]:
    """返回最近 n 年年报的资产负债率序列(小数 0~1),**升序**(最旧在前,[-1]=最新)。

    严格 PIT:只纳入 NOTICE_DATE ≤ ctx.current_date 的年报;按 REPORT_DATE 去重
    (保留最新披露版本)保证是不同财年。任一年负债率无法计算 → 返 None(YoY 需连续)。
    数据不足 n 年 → 返 None。
    """
    cur_date = getattr(ctx, "current_date", None)
    if cur_date is None:
        return None
    market = getattr(ctx, "market", None) or "A"
    lookup = _get(market)
    g = lookup.get(symbol)
    if g is None or g.empty:
        return None
    # PIT:NOTICE_DATE ≤ cur(ISO 日期串,字典序即时间序;与 growth_long searchsorted 同口径)
    vis = g[g["NOTICE_DATE"].values <= cur_date]
    if vis.empty:
        return None
    # 按 REPORT_DATE 去重,保留最新披露的重述版本 → 不同财年
    vis = vis.sort_values("NOTICE_DATE").drop_duplicates("REPORT_DATE", keep="last")
    vis = vis.sort_values("REPORT_DATE")
    if len(vis) < n_years:
        return None
    tail = vis.tail(n_years)
    ratios: list[float] = []
    for _, r in tail.iterrows():
        ratio = _row_debt_ratio(r)
        if ratio is None:
            return None
        ratios.append(ratio)
    return ratios


def is_deleveraging(
    ctx, symbol: str, *, min_drop: float = 0.0, lookback: int = 2
) -> Optional[bool]:
    """最新一期负债率是否较 lookback 期前**下降**(去杠杆)。

    - lookback=2(默认):比较最新年报与上年年报。
    - min_drop:要求下降幅度(负债率点数,小数)≥ 此值。如 0.02 = 至少降 2 个百分点;
      0 = 只要下降即可。
    返回:
      None — 数据不足
      True — 负债率下降 ≥ min_drop(资产负债表改善)
      False — 未下降 / 下降不足
    """
    ratios = get_debt_ratios(ctx, symbol, n_years=lookback)
    if ratios is None or len(ratios) < 2:
        return None
    latest = ratios[-1]
    prev = ratios[0]  # lookback 期前
    drop = prev - latest  # 正 = 去杠杆
    return bool(drop >= max(min_drop, 0.0) and drop > 0.0) if min_drop > 0 else bool(drop > 0.0)


def get_latest_debt_ratio(ctx, symbol: str) -> Optional[float]:
    """最新一期(PIT)资产负债率(小数 0~1)。数据缺失返 None。

    与 quality.get_debt_ratio 同口径(小数),但**走 NOTICE_DATE 严格 PIT**,
    月度调仓下无 REPORT_DATE as-of 前视。
    """
    ratios = get_debt_ratios(ctx, symbol, n_years=1)
    if not ratios:
        return None
    return ratios[-1]


# ══════════════════════════════════════════════════════════════════════════
# 隐蔽资产型(Asset Plays)取数:有形账面价值折价 + 净现金(NOTICE_DATE 严格 PIT)
# ══════════════════════════════════════════════════════════════════════════

def _latest_visible_annual_row(ctx, symbol: str):
    """最新一期(PIT)年报行(pandas Series)。数据缺失返 None。

    与 get_debt_ratios 同口径的严格 PIT:仅纳入 NOTICE_DATE ≤ ctx.current_date 的年报,
    按 REPORT_DATE 去重(保留最新披露的重述版本),取最新财年那一行。
    """
    cur_date = getattr(ctx, "current_date", None)
    if cur_date is None:
        return None
    market = getattr(ctx, "market", None) or "A"
    lookup = _get(market)
    g = lookup.get(symbol)
    if g is None or g.empty:
        return None
    vis = g[g["NOTICE_DATE"].values <= cur_date]
    if vis.empty:
        return None
    vis = vis.sort_values("NOTICE_DATE").drop_duplicates("REPORT_DATE", keep="last")
    vis = vis.sort_values("REPORT_DATE")
    return vis.iloc[-1]


def get_tangible_equity(ctx, symbol: str) -> Optional[float]:
    """最新 PIT 年报**有形账面价值**(元)= 归母权益 − 商誉 − 无形资产。

    隐蔽资产型「剔虚」的核心:剔掉商誉/无形这类无变现价值、易减值的软资产,
    只认扎实的有形净资产。归母权益(TOTAL_PARENT_EQUITY)缺失 → 返 None;
    商誉/无形缺失按 0 处理(多数无商誉的公司该字段为空,视作无可剔)。
    """
    row = _latest_visible_annual_row(ctx, symbol)
    if row is None:
        return None
    eq = row.get("TOTAL_PARENT_EQUITY")
    if eq is None or pd.isna(eq):
        return None
    goodwill = row.get("GOODWILL")
    goodwill = 0.0 if goodwill is None or pd.isna(goodwill) else float(goodwill)
    intangible = row.get("INTANGIBLE_ASSET")
    intangible = 0.0 if intangible is None or pd.isna(intangible) else float(intangible)
    return float(eq) - goodwill - intangible


def get_net_cash(ctx, symbol: str) -> Optional[float]:
    """最新 PIT 年报**净现金**(元)= 货币资金 − 总负债。

    格雷厄姆/林奇口径的「钱袋子」硬资产:>0 表示账上现金足以偿清全部负债后仍有剩余。
    货币资金(MONETARYFUNDS)或总负债(TOTAL_LIABILITIES)缺失 → 返 None。
    注:仅用货币资金(不含交易性金融资产/其他流动资产),保守口径。
    """
    row = _latest_visible_annual_row(ctx, symbol)
    if row is None:
        return None
    cash = row.get("MONETARYFUNDS")
    liab = row.get("TOTAL_LIABILITIES")
    if cash is None or pd.isna(cash) or liab is None or pd.isna(liab):
        return None
    return float(cash) - float(liab)
