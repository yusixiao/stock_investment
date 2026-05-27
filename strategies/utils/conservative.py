"""现金流保守策略 — 粗算回报率 R + Layer 2 否决项 utils。

⚠️ 重要边界(2026-05-27):
    本模块**只**实现 cpa Phase 3.1 因子2 "粗算 R"(R = NP × M × (1−Q) / 市值),
    它是机械化可计算的近似。**不**实现需要 LLM 11 步精算才能产出的真实 GG / KK
    (那需要对会计政策、行业特征、附注披露做定性判断,SQL 写不出来)。

    请勿把本模块当作 cpa 估值结果。完整 cpa 流程见
    `backend/services/agent/agents/cpa/prompts/phase3_quantitative.md`。

公式(`shared_tables.md`):
    A 股(长期持有,Q=0):R = NP × M / 市值 × 100%
    门槛 II = max(3.5%, Rf + 2%) = max(3.5, 4.7) = 4.7%

Layer 2 否决项弥补"粗算 R"的盲点:
    - 金融股直接排除(cpa 框架对金融业有方法论盲点,FCFF_BACK 不适用)
    - 商誉 / 归母权益 > 30% → 减值高风险
    - 净现金转负 → 流动性恶化
    - 近 2 年年报 FCF 都 ≤ 0 → 现金流不健康
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

# 与 cpa Phase 1 §14(s14_rf.py)对齐
RF_CHINA_10Y: float = 0.027

# A 股门槛 II = max(3.5%, Rf + 2%);Rf=2.7% → max(3.5, 4.7) = 4.7
THRESHOLD_A_PCT: float = max(3.5, RF_CHINA_10Y * 100 + 2.0)

# 默认安全边际(JJ_粗 ≥ 0.5pct,与 cpa 仓位矩阵观察区间下限一致)
DEFAULT_SAFETY_MARGIN_PCT: float = 0.5

_FINANCIAL_INDUSTRY_KEYWORDS = ("银行", "保险", "证券")


def _safe_float(x) -> float | None:
    """把任意值安全转 float;None / NaN / 解析失败 → None。"""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


# ---------- 支付率 ----------


def compute_payout_ratio_3y(ctx, symbol: str) -> float | None:
    """近 3 年支付率均值 M(0-1 浮点;0.5 表示 50%)。

    口径(对齐 `shared_tables.md`):
      年度支付率 = 年度 DPS / 年度 EPSJB(基本每股收益)
      M = 近 3 个年报年的支付率算术均值(同币种,无需总股本)

    返回 None 条件:
      - financial_annual_history 不可达
      - dividend 表缺失或全部年份无派息
      - 近 3 年累计 EPS ≤ 0(亏损公司不算 M)
    """
    history = ctx.get_financial_annual_history(symbol, 3)
    if not history:
        return None
    eps_list: list[tuple[int, float]] = []
    for row in history:
        date = str(row.get("REPORT_DATE", ""))
        if len(date) < 4:
            continue
        try:
            year = int(date[:4])
        except ValueError:
            continue
        eps = _safe_float(row.get("EPSJB"))
        if eps is None:
            continue
        eps_list.append((year, eps))
    if len(eps_list) == 0:
        return None
    if sum(eps for _, eps in eps_list) <= 0:
        return None

    div_df = ctx.get_dividend(symbol)
    if div_df is None or len(div_df) == 0:
        return None
    if "date" not in div_df.columns or "cash_dividend" not in div_df.columns:
        return None

    # 按年汇总 cash_dividend(每股派息)
    tmp = div_df[["date", "cash_dividend"]].copy()
    tmp["cash_dividend"] = pd.to_numeric(tmp["cash_dividend"], errors="coerce")
    tmp = tmp.dropna(subset=["cash_dividend"])
    tmp["year"] = tmp["date"].astype(str).str[:4]
    tmp = tmp[tmp["year"].str.len() >= 4]
    try:
        tmp["year"] = tmp["year"].astype(int)
    except ValueError:
        return None
    grouped = tmp.groupby("year")["cash_dividend"].sum().to_dict()

    ratios: list[float] = []
    for year, eps in eps_list:
        if eps <= 0:
            continue  # 亏损年不计入支付率均值
        dps = float(grouped.get(year, 0.0))
        if dps <= 0:
            continue
        ratios.append(dps / eps)
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


# ---------- 粗算 R ----------


def compute_r(ctx, symbol: str) -> float | None:
    """穿透回报率粗算 R(单位 pct,如 5.20 表示 5.2%)。A 股口径(Q=0)。

    R = NP × M / 市值 × 100%
      NP = 最新年报 PARENTNETPROFIT(归母净利润)
      M  = compute_payout_ratio_3y
      市值 = 当前 close × TOTAL_SHARE

    返回 None:任一数据缺失 / NP ≤ 0 / 市值 ≤ 0。
    """
    fin = ctx.get_financial_annual(symbol)
    if fin is None:
        return None
    np_value = _safe_float(fin.get("PARENTNETPROFIT"))
    total_share = _safe_float(fin.get("TOTAL_SHARE"))
    if np_value is None or np_value <= 0:
        return None
    if total_share is None or total_share <= 0:
        return None

    m = compute_payout_ratio_3y(ctx, symbol)
    if m is None:
        return None

    price = ctx.get_price(symbol)
    if price is None:
        return None
    close = _safe_float(price.get("close")) if isinstance(price, dict) else None
    if close is None or close <= 0:
        return None

    market_cap = close * total_share
    if market_cap <= 0:
        return None
    return (np_value * m) / market_cap * 100.0


def filter_by_r(
    ctx,
    symbols: Iterable[str],
    *,
    threshold_pct: float = THRESHOLD_A_PCT + DEFAULT_SAFETY_MARGIN_PCT,
) -> list[str]:
    """筛选粗算 R ≥ threshold_pct 的股票。

    默认门槛 = 4.7 + 0.5 = 5.2pct(A 股 II + 安全边际)。
    stage = "conservative.r"
    """
    stage = "conservative.r"
    result: list[str] = []
    in_list = list(symbols)
    for sym in in_list:
        r = compute_r(ctx, sym)
        if r is None:
            ctx.log_reject(sym, stage, "no_data", threshold=threshold_pct)
            continue
        ctx.record_factor(sym, "R_pct", round(r, 3))
        if r >= threshold_pct:
            ctx.log_pass(sym, stage, r_pct=r, threshold=threshold_pct)
            result.append(sym)
        else:
            ctx.log_reject(
                sym, stage, "below_threshold", r_pct=r, threshold=threshold_pct
            )
    ctx.log_flow(stage, input=len(in_list), passed=len(result))
    return result


# ---------- Layer 2 否决项 ----------


def reject_financial_industry(ctx, symbols: Iterable[str]) -> list[str]:
    """金融股(银行/保险/证券)排除。

    cpa 框架对金融业方法论盲点(FCFF_BACK 不适用),直接整类排除。
    INDUSTRY_NAME 缺失时**保守放行**(避免误杀小众行业)。
    stage = "conservative.industry_filter"
    """
    stage = "conservative.industry_filter"
    result: list[str] = []
    in_list = list(symbols)
    for sym in in_list:
        bal = ctx.get_balance(sym)
        industry = ""
        if bal is not None:
            industry = str(bal.get("INDUSTRY_NAME") or "")
        if any(kw in industry for kw in _FINANCIAL_INDUSTRY_KEYWORDS):
            ctx.log_reject(sym, stage, "financial_industry", industry=industry)
            continue
        ctx.log_pass(sym, stage, industry=industry)
        result.append(sym)
    ctx.log_flow(stage, input=len(in_list), passed=len(result))
    return result


def reject_high_goodwill(
    ctx, symbols: Iterable[str], *, max_ratio: float = 0.30
) -> list[str]:
    """商誉 / 归母权益 > max_ratio 否决。

    数据缺失保守放行;归母权益 ≤ 0(资不抵债)直接否决。
    stage = "conservative.goodwill"
    """
    stage = "conservative.goodwill"
    result: list[str] = []
    in_list = list(symbols)
    for sym in in_list:
        bal = ctx.get_balance(sym)
        if bal is None:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        goodwill = _safe_float(bal.get("GOODWILL"))
        equity = _safe_float(bal.get("TOTAL_PARENT_EQUITY"))
        if goodwill is None and equity is None:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        if equity is None or equity <= 0:
            ctx.log_reject(sym, stage, "negative_equity", equity=equity)
            continue
        gw = goodwill if goodwill is not None else 0.0
        ratio = gw / equity
        if ratio > max_ratio:
            ctx.log_reject(
                sym, stage, "above_threshold", ratio=ratio, threshold=max_ratio
            )
            continue
        ctx.record_factor(sym, "商誉占比", round(ratio, 3))
        ctx.log_pass(sym, stage, ratio=ratio, threshold=max_ratio)
        result.append(sym)
    ctx.log_flow(stage, input=len(in_list), passed=len(result))
    return result


def reject_negative_net_cash(ctx, symbols: Iterable[str]) -> list[str]:
    """净现金 = MONETARYFUNDS − TOTAL_LIABILITIES < 0 否决。

    数据缺失保守放行。
    stage = "conservative.net_cash"
    """
    stage = "conservative.net_cash"
    result: list[str] = []
    in_list = list(symbols)
    for sym in in_list:
        bal = ctx.get_balance(sym)
        if bal is None:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        cash = _safe_float(bal.get("MONETARYFUNDS"))
        liab = _safe_float(bal.get("TOTAL_LIABILITIES"))
        if cash is None or liab is None:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        net = cash - liab
        if net < 0:
            ctx.log_reject(sym, stage, "negative_net_cash", net_cash=net)
            continue
        ctx.log_pass(sym, stage, net_cash=net)
        result.append(sym)
    ctx.log_flow(stage, input=len(in_list), passed=len(result))
    return result


def reject_negative_fcf_2y(ctx, symbols: Iterable[str]) -> list[str]:
    """近 2 年年报 FCF (NETCASH_OPERATE − CONSTRUCT_LONG_ASSET) 都 ≤ 0 → 否决。

    只要近 2 年里有 1 年 FCF > 0 就通过(避免单年异常误杀)。
    history 不可达 / 不足 2 期 → 保守放行。
    stage = "conservative.fcf_2y"
    """
    stage = "conservative.fcf_2y"
    result: list[str] = []
    in_list = list(symbols)
    for sym in in_list:
        history = ctx.get_cashflow_annual_history(sym, 2)
        if not history or len(history) < 2:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        fcfs: list[float] = []
        for row in history:
            op = _safe_float(row.get("NETCASH_OPERATE"))
            capex = _safe_float(row.get("CONSTRUCT_LONG_ASSET"))
            if op is None:
                continue
            cap = capex if capex is not None else 0.0
            fcfs.append(op - cap)
        if not fcfs:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        if all(f <= 0 for f in fcfs):
            ctx.log_reject(sym, stage, "fcf_persistent_negative", fcfs=fcfs)
            continue
        ctx.log_pass(sym, stage, fcfs=fcfs)
        result.append(sym)
    ctx.log_flow(stage, input=len(in_list), passed=len(result))
    return result
