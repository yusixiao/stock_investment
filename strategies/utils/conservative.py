"""现金流保守策略 — 粗算回报率 R + Layer 2 否决项 + L1.3 信誉评级 utils。

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
    - ROE 三年下降 > 30% → 盈利能力恶化(L2 第 5 项,2026-05-27)

L3 仓位矩阵(2026-05-28 重写为 CPA 原口径 4 档):
    三维查找表 f(R, credibility, trap_rating) → tier ∈ {full, p70, observe, skip}
    粗算版用 R 替代 cpa 精算 KK,把"粗算安全边际"= R − threshold 对标 CPA 的 KK。
    full_bonus = 1.5pct(对齐 CPA 原文 KK ≥ 1.5pct 阈值)。

    用户口径(2026-05-28):KK 0.5~1.5pct 一律归 observe,不再有 50% 这一档。
    所以 50% 这一档实际不会出现,用 4 档 {full, p70, observe, skip}。

    优先级(自上而下,首个命中即返回):
      1. cred==low → skip
      2. R 缺失 / R<门槛(KK<0)→ skip
      3. trap==high → observe(任何 R 都不买,只观察)
      4. R≥门槛+1.5(KK≥1.5)+ cred=high + trap=low → full(100%)
      5. R≥门槛+1.5 + cred=high + trap=mid → p70(70%)
      6. R≥门槛+1.5 + cred=mid + trap=low → p70(70%)
      7. 其他(含 KK 0~1.5pct 区间)→ observe

L2.5 trap_rating 软评分(2026-05-27):
    把 L2.2-L2.5 四项(商誉/净现金/FCF/ROE 下降)从硬否决聚合为 low/mid/high
    金融股(L2.1)仍硬否决,不参与软评分(cpa 框架方法论盲点)
    触发 0 → low,1 → mid,≥2 → high;数据缺失 = 未触发(保守语义)

L1.3 信誉评级(2026-05-27):
    三维度聚合 → high / mid / low:
    - 维度1: 5 年营收 CV(变异系数 = 标准差/均值,越低越稳)
    - 维度2: 利润调整幅度(非经常损益占比 = |归母 − 扣非| / |归母|)
    - 维度3: λ warning(高杠杆/商誉/净现金/FCF 四项检查命中数)
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


def reject_low_fcf_yield(
    ctx, symbols: Iterable[str], *, threshold: float = 0.05
) -> list[str]:
    """最新年报 FCF / 当前市值 < threshold(默认 5%)→ 否决。

    对齐 CPA on_sell 规则 2(critical):FCF yield < 5% → 清仓。
    若入场时已 < 5%,会立即被 on_sell 清仓 → 此处必须硬过滤。

    口径:
      FCF = NETCASH_OPERATE − CONSTRUCT_LONG_ASSET(最新年报)
      market_cap = close(当前 bar)× TOTAL_SHARE(最新年报)
      yield = FCF / market_cap

    保守放行情形:
      - cashflow / financial / price 任一不可达 → 通过(no_data)
      - market_cap ≤ 0 → 通过
    stage = "conservative.fcf_yield"
    """
    stage = "conservative.fcf_yield"
    result: list[str] = []
    in_list = list(symbols)
    for sym in in_list:
        cf = ctx.get_cashflow_annual(sym)
        if cf is None:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        op = _safe_float(cf.get("NETCASH_OPERATE"))
        capex = _safe_float(cf.get("CONSTRUCT_LONG_ASSET"))
        if op is None:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        fcf = op - (capex if capex is not None else 0.0)

        fin = ctx.get_financial_annual(sym)
        total_share = _safe_float(fin.get("TOTAL_SHARE")) if fin else None
        price = ctx.get_price(sym)
        close = _safe_float(price.get("close")) if isinstance(price, dict) else None
        if total_share is None or total_share <= 0 or close is None or close <= 0:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        market_cap = close * total_share
        if market_cap <= 0:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        fcf_yield = fcf / market_cap
        if fcf_yield < threshold:
            ctx.log_reject(
                sym,
                stage,
                "fcf_yield_below_threshold",
                fcf_yield=fcf_yield,
                threshold=threshold,
            )
            continue
        ctx.log_pass(sym, stage, fcf_yield=fcf_yield)
        result.append(sym)
    ctx.log_flow(stage, input=len(in_list), passed=len(result))
    return result


def reject_roe_decline_3y(
    ctx, symbols: Iterable[str], *, max_decline: float = 0.30
) -> list[str]:
    """近 3 年 ROEJQ 相对降幅 > max_decline → 否决(L2 第 5 项)。

    口径:
      取近 3 年年报 ROEJQ(百分比单位,如 15.0 = 15%)
      相对降幅 = (ROE_oldest − ROE_latest) / |ROE_oldest|
      > max_decline(默认 30%)→ 否决,否则记录因子并通过

    保守放行情形:
      - financial history 不可达 / 不足 3 个有效样本
      - 起始 ROE ≤ 0(亏损或扭亏,降幅口径失真)
    stage = "conservative.roe_decline"
    """
    stage = "conservative.roe_decline"
    result: list[str] = []
    in_list = list(symbols)
    for sym in in_list:
        history = ctx.get_financial_annual_history(sym, 3)
        if not history or len(history) < 3:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        # history 按日期降序,index 0 = 最新
        roes: list[float] = []
        for row in history:
            v = _safe_float(row.get("ROEJQ"))
            if v is not None:
                roes.append(v)
        if len(roes) < 3:
            ctx.log_pass(sym, stage, reason="no_data")
            result.append(sym)
            continue
        latest = roes[0]
        oldest = roes[-1]
        if oldest <= 0:
            ctx.log_pass(sym, stage, reason="non_positive_oldest", oldest=oldest)
            result.append(sym)
            continue
        decline = (oldest - latest) / abs(oldest)
        if decline > max_decline:
            ctx.log_reject(
                sym,
                stage,
                "roe_decline_exceeds",
                decline=decline,
                threshold=max_decline,
                latest=latest,
                oldest=oldest,
            )
            continue
        ctx.record_factor(sym, "roe_decline_pct", round(decline, 4))
        ctx.log_pass(sym, stage, decline=decline, threshold=max_decline)
        result.append(sym)
    ctx.log_flow(stage, input=len(in_list), passed=len(result))
    return result


# ---------- L2.5 trap_rating 软评分 ----------


def _is_goodwill_triggered(ctx, symbol: str) -> bool:
    """商誉占比 > 30% 或归母权益 ≤ 0 → True。数据完全缺失 → False。"""
    bal = ctx.get_balance(symbol)
    if bal is None:
        return False
    goodwill = _safe_float(bal.get("GOODWILL"))
    equity = _safe_float(bal.get("TOTAL_PARENT_EQUITY"))
    if goodwill is None and equity is None:
        return False
    if equity is not None and equity <= 0:
        return True
    if equity is None or equity == 0:
        return False
    gw = goodwill if goodwill is not None else 0.0
    return (gw / equity) > 0.30


def _is_net_cash_triggered(ctx, symbol: str) -> bool:
    """净现金 < 0 → True。任一字段缺失 → False。"""
    bal = ctx.get_balance(symbol)
    if bal is None:
        return False
    cash = _safe_float(bal.get("MONETARYFUNDS"))
    liab = _safe_float(bal.get("TOTAL_LIABILITIES"))
    if cash is None or liab is None:
        return False
    return (cash - liab) < 0


def _is_fcf_negative_2y_triggered(ctx, symbol: str) -> bool:
    """近 2 年 FCF 都 ≤ 0 → True。数据不足 2 年 → False。"""
    history = ctx.get_cashflow_annual_history(symbol, 2)
    if not history or len(history) < 2:
        return False
    fcfs: list[float] = []
    for row in history:
        op = _safe_float(row.get("NETCASH_OPERATE"))
        capex = _safe_float(row.get("CONSTRUCT_LONG_ASSET"))
        if op is None:
            continue
        cap = capex if capex is not None else 0.0
        fcfs.append(op - cap)
    if len(fcfs) < 2:
        return False
    return all(f <= 0 for f in fcfs)


def _is_roe_decline_3y_triggered(ctx, symbol: str, max_decline: float = 0.30) -> bool:
    """近 3 年 ROEJQ 相对降幅 > max_decline → True。数据不足/起始 ROE ≤ 0 → False。"""
    history = ctx.get_financial_annual_history(symbol, 3)
    if not history or len(history) < 3:
        return False
    roes: list[float] = []
    for row in history:
        v = _safe_float(row.get("ROEJQ"))
        if v is not None:
            roes.append(v)
    if len(roes) < 3:
        return False
    latest, oldest = roes[0], roes[-1]
    if oldest <= 0:
        return False
    return ((oldest - latest) / abs(oldest)) > max_decline


def compute_trap_rating(
    ctx, symbol: str, *, max_roe_decline: float = 0.30
) -> tuple[str, list[str]]:
    """L2.5 trap_rating 软评分聚合 → ("low"/"mid"/"high", triggered_keys)。

    检查 4 项(金融股不参与,L2.1 仍走硬否决):
      - "goodwill"     — 商誉 / 归母权益 > 30%
      - "net_cash"     — 货币资金 < 总负债
      - "fcf"          — 近 2 年年报 FCF 都 ≤ 0
      - "roe_decline"  — 近 3 年 ROE 相对降幅 > max_roe_decline

    聚合规则:
      触发 0 → low(健康)
      触发 1 → mid(警惕)
      触发 ≥2 → high(高风险)

    数据缺失维度计为"未触发"(对齐保守放行语义)。
    """
    triggered: list[str] = []
    if _is_goodwill_triggered(ctx, symbol):
        triggered.append("goodwill")
    if _is_net_cash_triggered(ctx, symbol):
        triggered.append("net_cash")
    if _is_fcf_negative_2y_triggered(ctx, symbol):
        triggered.append("fcf")
    if _is_roe_decline_3y_triggered(ctx, symbol, max_decline=max_roe_decline):
        triggered.append("roe_decline")

    n = len(triggered)
    if n == 0:
        rating = "low"
    elif n == 1:
        rating = "mid"
    else:
        rating = "high"
    return rating, triggered


def record_trap_rating(
    ctx, symbols: Iterable[str], *, max_roe_decline: float = 0.30
) -> None:
    """批量记录 L2.5 trap_rating(不筛除,只记录因子)。

    供 L3 仓位矩阵作为输入维度;策略层可通过单独开关决定是否启用软评分模式
    替代硬否决。
    stage = "conservative.trap_rating"
    """
    stage = "conservative.trap_rating"
    in_list = list(symbols)
    for sym in in_list:
        rating, triggered = compute_trap_rating(
            ctx, sym, max_roe_decline=max_roe_decline
        )
        ctx.record_factor(sym, "trap_rating", rating)
        ctx.record_factor(sym, "trap_triggered_count", len(triggered))
        ctx.record_factor(
            sym, "trap_triggered", ",".join(triggered) if triggered else ""
        )
        ctx.log_pass(sym, stage, rating=rating, triggered=triggered)
    ctx.log_flow(stage, input=len(in_list))


# ---------- L1.3 信誉评级 ----------


def _compute_revenue_cv_5y(ctx, symbol: str) -> float | None:
    """5 年营收变异系数(CV = 标准差 / |均值|)。

    数据源:income 年报 TOTAL_OPERATE_INCOME。
    返回 None:数据不足(<3 年)或均值 ≈ 0。
    """
    history = ctx.get_income_annual_history(symbol, 5)
    if not history or len(history) < 3:
        return None
    revenues: list[float] = []
    for row in history:
        v = _safe_float(row.get("TOTAL_OPERATE_INCOME"))
        if v is not None:
            revenues.append(v)
    if len(revenues) < 3:
        return None
    mean_val = sum(revenues) / len(revenues)
    if abs(mean_val) < 1e-8:
        return None
    variance = sum((v - mean_val) ** 2 for v in revenues) / len(revenues)
    return variance**0.5 / abs(mean_val)


def _compute_profit_adjustment_5y(ctx, symbol: str) -> float | None:
    """5 年利润调整幅度(非经常损益占比均值)。

    口径:每年 |PARENT_NETPROFIT − DEDUCT_PARENT_NETPROFIT| / |PARENT_NETPROFIT|
    取近 5 年均值。越低说明利润质量越高(扣非与归母接近)。
    返回 None:数据不足或归母净利润均值 ≈ 0。
    """
    history = ctx.get_income_annual_history(symbol, 5)
    if not history or len(history) < 3:
        return None
    ratios: list[float] = []
    for row in history:
        parent = _safe_float(row.get("PARENT_NETPROFIT"))
        deduct = _safe_float(row.get("DEDUCT_PARENT_NETPROFIT"))
        if parent is None or deduct is None:
            continue
        if abs(parent) < 1e-8:
            continue
        ratios.append(abs(parent - deduct) / abs(parent))
    if len(ratios) < 2:
        return None
    return sum(ratios) / len(ratios)


def _count_lambda_warnings(ctx, symbol: str) -> int:
    """λ warning 计数(对齐 §13 自检逻辑)。

    四项检查:
    1. 资产负债率 > 80%(高杠杆)
    2. 商誉 > 归母权益 30%(减值风险)
    3. 净现金 < 0(流动性恶化)
    4. 近 2 年 FCF 持续为负
    """
    count = 0
    # 1. 高杠杆
    bal = ctx.get_balance(symbol)
    if bal is not None:
        debt_ratio = _safe_float(bal.get("DEBT_ASSET_RATIO"))
        if debt_ratio is not None and debt_ratio > 80:
            count += 1
    # 2. 商誉占比
    if bal is not None:
        goodwill = _safe_float(bal.get("GOODWILL"))
        equity = _safe_float(bal.get("TOTAL_PARENT_EQUITY"))
        if goodwill is not None and equity is not None and equity > 0:
            if goodwill / equity > 0.30:
                count += 1
    # 3. 净现金转负
    if bal is not None:
        cash = _safe_float(bal.get("MONETARYFUNDS"))
        liab = _safe_float(bal.get("TOTAL_LIABILITIES"))
        if cash is not None and liab is not None and cash - liab < 0:
            count += 1
    # 4. FCF 持续为负
    history = ctx.get_cashflow_annual_history(symbol, 2)
    if history and len(history) >= 2:
        fcfs: list[float] = []
        for row in history:
            op = _safe_float(row.get("NETCASH_OPERATE"))
            capex = _safe_float(row.get("CONSTRUCT_LONG_ASSET"))
            if op is not None:
                cap = capex if capex is not None else 0.0
                fcfs.append(op - cap)
        if len(fcfs) >= 2 and all(f <= 0 for f in fcfs):
            count += 1
    return count


def compute_credibility_rating(ctx, symbol: str) -> str:
    """L1.3 信誉评级 → "high" / "mid" / "low"。

    三维度评分规则:
    - 维度1(营收 CV):< 0.15 → A, 0.15~0.30 → B, > 0.30 → C
    - 维度2(利润调整幅度):< 0.10 → A, 0.10~0.25 → B, > 0.25 → C
    - 维度3(λ warning):0 → A, 1 → B, ≥ 2 → C

    聚合:3 个 A → high, 含 C → low, 其余 → mid。
    数据缺失维度计为 B(中性)。
    """
    scores: list[str] = []

    cv = _compute_revenue_cv_5y(ctx, symbol)
    if cv is None:
        scores.append("B")
    elif cv < 0.15:
        scores.append("A")
    elif cv <= 0.30:
        scores.append("B")
    else:
        scores.append("C")

    adj = _compute_profit_adjustment_5y(ctx, symbol)
    if adj is None:
        scores.append("B")
    elif adj < 0.10:
        scores.append("A")
    elif adj <= 0.25:
        scores.append("B")
    else:
        scores.append("C")

    warnings = _count_lambda_warnings(ctx, symbol)
    if warnings == 0:
        scores.append("A")
    elif warnings == 1:
        scores.append("B")
    else:
        scores.append("C")

    if all(s == "A" for s in scores):
        rating = "high"
    elif "C" in scores:
        rating = "low"
    else:
        rating = "mid"

    ctx.record_factor(symbol, "credibility_rating", rating)
    ctx.record_factor(symbol, "revenue_cv", round(cv, 4) if cv is not None else None)
    ctx.record_factor(
        symbol, "profit_adjustment", round(adj, 4) if adj is not None else None
    )
    ctx.record_factor(symbol, "lambda_warnings", warnings)
    return rating


def record_credibility_factors(ctx, symbols: Iterable[str]) -> None:
    """批量记录 L1.3 信誉评级因子(不筛除,只记录)。

    供策略 screen() 调用,因子值在雷达扫描结果中展示。
    stage = "conservative.credibility"
    """
    stage = "conservative.credibility"
    in_list = list(symbols)
    for sym in in_list:
        rating = compute_credibility_rating(ctx, sym)
        ctx.log_pass(sym, stage, rating=rating)
    ctx.log_flow(stage, input=len(in_list))


# ---------- L3 仓位矩阵 ----------

# 默认门槛与粗算 R 的 filter_by_r 一致
_DEFAULT_TIER_THRESHOLD_PCT: float = THRESHOLD_A_PCT + DEFAULT_SAFETY_MARGIN_PCT  # 5.2
# full 加成 = CPA 原文 KK ≥ 1.5pct 阈值(2026-05-28 由 2.0 改 1.5,对齐 CPA)
_DEFAULT_TIER_FULL_BONUS_PCT: float = 1.5

# CPA 仓位百分比口径(供 buyer 落地用)
TIER_PCT: dict[str, float] = {
    "full": 1.0,  # 100% × max_per_stock_pct
    "p70": 0.7,  # 70%  × max_per_stock_pct
    "observe": 0.0,
    "skip": 0.0,
}


def compute_position_tier(
    r_pct: float | None,
    credibility: str | None,
    trap_rating: str | None,
    *,
    threshold_pct: float = _DEFAULT_TIER_THRESHOLD_PCT,
    full_bonus_pct: float = _DEFAULT_TIER_FULL_BONUS_PCT,
) -> str:
    """三维查表 → "full" / "p70" / "observe" / "skip"(CPA 原口径 4 档)。

    优先级(自上而下,首个命中即返回):
      1. credibility == "low"            → skip(信誉差,直接拒绝)
      2. r_pct 缺失 / < threshold_pct    → skip(KK<0,估值不达标)
      3. trap_rating == "high"           → observe(陷阱风险高,只观察)
      4. R ≥ threshold+full_bonus + cred=high + trap=low → full
      5. R ≥ threshold+full_bonus + cred=high + trap=mid → p70
      6. R ≥ threshold+full_bonus + cred=mid  + trap=low → p70
      7. 其他(含 KK 0~1.5pct 区间)        → observe

    未知 credibility / trap_rating 字符串退化为 mid(防御式)。
    """
    # 规范化输入
    cred = (credibility or "").lower()
    trap = (trap_rating or "").lower()
    if cred not in ("high", "mid", "low"):
        cred = "mid"
    if trap not in ("high", "mid", "low"):
        trap = "mid"

    # 1. cred=low 直接 skip
    if cred == "low":
        return "skip"
    # 2. R 缺失 / 不达标
    if r_pct is None or r_pct < threshold_pct:
        return "skip"
    # 3. trap=high → observe
    if trap == "high":
        return "observe"

    full_threshold = threshold_pct + full_bonus_pct
    # 4. full(高 R + 高 cred + 低 trap)
    if r_pct >= full_threshold and cred == "high" and trap == "low":
        return "full"
    # 5. p70(高 R + 高 cred + 中 trap)
    if r_pct >= full_threshold and cred == "high" and trap == "mid":
        return "p70"
    # 6. p70(高 R + 中 cred + 低 trap)
    if r_pct >= full_threshold and cred == "mid" and trap == "low":
        return "p70"
    # 7. 其他(含 KK 0~1.5pct 区间;含 mid+mid 等组合)→ observe
    return "observe"


def record_position_tier(
    ctx,
    symbols: Iterable[str],
    *,
    threshold_pct: float = _DEFAULT_TIER_THRESHOLD_PCT,
    full_bonus_pct: float = _DEFAULT_TIER_FULL_BONUS_PCT,
    include_observe: bool = False,
) -> list[str]:
    """L3 批量打 tier + 默认筛除 skip / observe(可选保留 observe)。

    依赖前置 factor:R_pct / credibility_rating / trap_rating
    任一缺失 → tier = "skip"(无估值依据,默认拒绝)。
    保留池 = {full, p70}(默认),include_observe=True 时加入 observe(只观察不买)。
    stage = "conservative.position_tier"
    """
    stage = "conservative.position_tier"
    in_list = list(symbols)
    pool: list[str] = []
    counters = {"full": 0, "p70": 0, "observe": 0, "skip": 0}
    for sym in in_list:
        factors = ctx.get_factors(sym) if hasattr(ctx, "get_factors") else {}
        r_pct = factors.get("R_pct") if factors else None
        cred = factors.get("credibility_rating") if factors else None
        trap = factors.get("trap_rating") if factors else None
        # 前置因子缺失 → 直接 skip(无估值依据)
        if r_pct is None or cred is None or trap is None:
            tier = "skip"
        else:
            tier = compute_position_tier(
                _safe_float(r_pct),
                cred,
                trap,
                threshold_pct=threshold_pct,
                full_bonus_pct=full_bonus_pct,
            )
        ctx.record_factor(sym, "position_tier", tier)
        counters[tier] = counters.get(tier, 0) + 1

        keep = tier in ("full", "p70") or (include_observe and tier == "observe")
        if keep:
            ctx.log_pass(sym, stage, tier=tier)
            pool.append(sym)
        else:
            ctx.log_reject(sym, stage, "tier_excluded", tier=tier)
    ctx.log_flow(stage, input=len(in_list), passed=len(pool), **counters)
    return pool
