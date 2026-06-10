"""质量过滤 utils — 用于价值策略的"价值陷阱"筛除层。

数据通路:
- 行业:`balance.INDUSTRY_NAME`(EastMoney F10,每期年报都带,稳定)
- 资产负债率:`balance.TOTAL_LIABILITIES / TOTAL_ASSETS`
- CFO/NP 比:`cashflow.NETCASH_OPERATE / income.PARENT_NETPROFIT`(年报 TTM 近似)
- ROE 趋势:`indicator.ROEJQ` 近 3 年序列

设计原则:
1. 数据缺失 → 返 None,**调用方决定**是放行还是淘汰(默认 passes_*=True 即放行)
2. 金融行业(银行/保险/证券)的资产负债率 ≥ 90% 是常态,debt_ratio 检查需要豁免
3. 所有读取走 `ctx.get_balance_annual / get_cashflow_annual_history / get_income_annual_history`,
   走 NOTICE_DATE-as-of 防前视(market_data 内部已处理)
"""

from __future__ import annotations

from typing import Optional

# 金融行业关键词:这些行业资产负债率天生 ≥ 90%(吸收存款/保费/客户保证金),
# 不应被 debt_ratio_max 杀掉。匹配方式:子串 in INDUSTRY_NAME。
_FINANCIAL_INDUSTRY_KEYWORDS = ("银行", "保险", "证券", "信托", "金融控股")


def get_industry(ctx, symbol: str) -> Optional[str]:
    """取最近年报的 INDUSTRY_NAME(EastMoney F10 一级行业,如「股份制银行」)。

    数据缺失 / 字段不存在 → None。
    """
    bal = ctx.get_balance_annual(symbol) if hasattr(ctx, "get_balance_annual") else None
    if bal is None:
        return None
    name = bal.get("INDUSTRY_NAME")
    if name is None or (isinstance(name, str) and not name.strip()):
        return None
    return str(name)


def is_financial_industry(industry_name: Optional[str]) -> bool:
    """判断行业是否属于金融业(资产负债率天然高,需要豁免)。"""
    if not industry_name:
        return False
    return any(kw in industry_name for kw in _FINANCIAL_INDUSTRY_KEYWORDS)


def get_debt_ratio(ctx, symbol: str) -> Optional[float]:
    """资产负债率 = TOTAL_LIABILITIES / TOTAL_ASSETS,数据缺失返 None。"""
    bal = ctx.get_balance_annual(symbol) if hasattr(ctx, "get_balance_annual") else None
    if bal is None:
        return None
    liab = bal.get("TOTAL_LIABILITIES")
    assets = bal.get("TOTAL_ASSETS")
    if liab is None or assets is None or assets <= 0:
        return None
    try:
        return float(liab) / float(assets)
    except (TypeError, ValueError):
        return None


def get_cfo_to_np_ratio(ctx, symbol: str) -> Optional[float]:
    """近一年报的 NETCASH_OPERATE / PARENT_NETPROFIT,数据缺失或净利润 ≤ 0 返 None。

    意义:剔除净利润主要靠应收账款堆积的"假利润"公司。
    健康公司通常 ≥ 0.8,< 0.5 是危险信号。
    """
    cf_hist = (
        ctx.get_cashflow_annual_history(symbol, 1)
        if hasattr(ctx, "get_cashflow_annual_history")
        else None
    )
    inc_hist = (
        ctx.get_income_annual_history(symbol, 1)
        if hasattr(ctx, "get_income_annual_history")
        else None
    )
    if not cf_hist or not inc_hist:
        return None
    cfo = cf_hist[0].get("NETCASH_OPERATE")
    np_ = inc_hist[0].get("PARENT_NETPROFIT")
    if cfo is None or np_ is None:
        return None
    try:
        np_f = float(np_)
        if np_f <= 0:
            # 净利润 ≤ 0 时 CFO/NP 无意义(策略上层应已用 ROE > 0 过滤)
            return None
        return float(cfo) / np_f
    except (TypeError, ValueError):
        return None


def get_cfo(ctx, symbol: str) -> Optional[float]:
    """近一年报经营性现金流绝对值,用于 CFO > 0 这种独立判断。"""
    cf_hist = (
        ctx.get_cashflow_annual_history(symbol, 1)
        if hasattr(ctx, "get_cashflow_annual_history")
        else None
    )
    if not cf_hist:
        return None
    cfo = cf_hist[0].get("NETCASH_OPERATE")
    if cfo is None:
        return None
    try:
        return float(cfo)
    except (TypeError, ValueError):
        return None


def has_severe_roe_decline(
    ctx, symbol: str, *, lookback_years: int = 3, drop_threshold: float = 0.30
) -> Optional[bool]:
    """检查近 lookback_years 是否出现 ROE 连续 2 年下降 ≥ drop_threshold(默认 30%)。

    实现:取近 N 年年报 ROEJQ,逐对比,任意一对相邻年(新→旧)
    如果 (旧 - 新) / 旧 ≥ drop_threshold 即记一次下降。连续 2 次下降 → True。

    返回:
      None — 数据不足(年报 < 3 年)
      True — 有连续 2 年大幅下滑(质量恶化信号)
      False — 健康
    """
    # 复用 financial._get_field_annual:这里我们要历史而非单期,直接走 cashflow_annual_history
    # 实际上 ROE 在 indicator 视图,需要 _financial_annual_history。MarketData 已暴露
    # get_financial_annual_history(用于 indicator)。
    if not hasattr(ctx, "get_financial_annual_history"):
        return None
    rows = ctx.get_financial_annual_history(symbol, lookback_years)
    if not rows or len(rows) < 3:
        return None
    # rows 倒序:[最新, 次新, ..., 最旧]
    roes = []
    for r in rows:
        v = r.get("ROEJQ")
        if v is None:
            return None
        try:
            roes.append(float(v))
        except (TypeError, ValueError):
            return None
    # 至少 3 个点:roes[0] 最新, roes[2] 最旧。
    # 检查相邻两对是否都下降 ≥ drop_threshold
    declines = []
    for i in range(len(roes) - 1):
        new_v = roes[i]
        old_v = roes[i + 1]
        if old_v <= 0:
            # 起点为负/零时不能算百分比下降,跳过
            declines.append(False)
            continue
        drop = (old_v - new_v) / old_v
        declines.append(drop >= drop_threshold)
    # 连续 2 次下降
    for i in range(len(declines) - 1):
        if declines[i] and declines[i + 1]:
            return True
    return False


def passes_quality_filter(
    ctx,
    symbol: str,
    *,
    require_positive_cfo: bool = True,
    cfo_to_np_min: Optional[float] = 0.5,
    debt_ratio_max: Optional[float] = 0.70,
    roe_decline_check: bool = True,
    roe_decline_lookback: int = 3,
    roe_decline_threshold: float = 0.30,
) -> tuple[bool, str]:
    """综合质量门槛,返回 (是否通过, 失败原因)。

    缺失数据 → 默认放行(返 True, "missing_<field>"),把决策权交给上层(可能用其他因子兜底)。
    金融行业自动豁免 debt_ratio 检查。
    """
    industry = get_industry(ctx, symbol)
    is_fin = is_financial_industry(industry)

    # 1. CFO > 0(银行/保险这条不适用,豁免:金融机构 CFO 受存款波动主导,负值是常态)
    if require_positive_cfo and not is_fin:
        cfo = get_cfo(ctx, symbol)
        if cfo is not None and cfo <= 0:
            return False, "negative_cfo"

    # 2. CFO/NP ≥ 阈值(金融业豁免)
    if cfo_to_np_min is not None and not is_fin:
        ratio = get_cfo_to_np_ratio(ctx, symbol)
        if ratio is not None and ratio < cfo_to_np_min:
            return False, f"low_cfo_np_ratio_{ratio:.2f}"

    # 3. 资产负债率 ≤ 阈值(金融业豁免)
    if debt_ratio_max is not None and not is_fin:
        dr = get_debt_ratio(ctx, symbol)
        if dr is not None and dr > debt_ratio_max:
            return False, f"high_debt_ratio_{dr:.2f}"

    # 4. ROE 不可连续 2 年大幅下滑
    if roe_decline_check:
        bad = has_severe_roe_decline(
            ctx,
            symbol,
            lookback_years=roe_decline_lookback,
            drop_threshold=roe_decline_threshold,
        )
        if bad is True:
            return False, "roe_severe_decline"

    return True, "ok"
