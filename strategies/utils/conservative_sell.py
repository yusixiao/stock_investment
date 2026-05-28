"""现金流保守策略 — 入场 baseline + CPA 7 条基本面止损规则。

⚠️ 边界(2026-05-28):
本模块实现 cpa Phase 3.2 §10.2 表格中 7 条**结构化**止损规则
(可机械化、可在 backtest 中触发)。**不**实现 §10.2 末尾"自然语言条件"
那一组(论点破坏类,需 LLM 判断)。

CPA 7 条结构化规则(`phase3_valuation.md` line 365-373):
    | # | 指标       | 条件                    | 严重度 |
    | 1 | 净现金     | < 0                     | critical |
    | 2 | FCF yield  | < 5%                    | critical |
    | 3 | FCF        | 连续 2 期 < 0           | critical |
    | 4 | 债务权益比 | > baseline×1.5 或 > 1.0 | warning  |
    | 5 | 营收同比   | < -20%                  | warning  |
    | 6 | 毛利率     | < baseline×0.8          | warning  |
    | 7 | 支付率     | 较 baseline 下降 > 30%  | warning  |

严重度处理(策略层映射,本模块只返回 severity 标签):
    critical → 清仓
    warning  → 减仓到当前 50%

baseline 字段:
    debt_equity   — 入场时点 D/E = TOTAL_LIABILITIES / TOTAL_PARENT_EQUITY
    gross_margin  — 入场时点 XSMLL(销售毛利率,百分比单位)
    payout        — 入场时点 compute_payout_ratio_3y(0-1 浮点)

数据缺失语义:
    baseline 字段缺失 → 对应规则跳过(不触发);保守:不让数据缺失误杀持仓。
    current 字段缺失 → 对应规则跳过(不触发)。
"""

from __future__ import annotations

from typing import Any

from strategies.utils.conservative import (
    _is_fcf_negative_2y_triggered,
    _is_net_cash_triggered,
    _safe_float,
    compute_payout_ratio_3y,
)


# --- 阈值常量 ---
FCF_YIELD_CRITICAL: float = 0.05  # 5%
DE_ABSOLUTE_CEILING: float = 1.0  # baseline 缺失时的绝对兜底
DE_BASELINE_MULTIPLIER: float = 1.5
REVENUE_YOY_WARNING: float = -0.20  # -20%
GROSS_MARGIN_BASELINE_RATIO: float = 0.80  # < baseline × 0.80
PAYOUT_DECLINE_THRESHOLD: float = 0.30  # 相对降幅 > 30%


# ---------- baseline 记录 ----------


def _compute_debt_equity(ctx, symbol: str) -> float | None:
    bal = ctx.get_balance(symbol)
    if bal is None:
        return None
    liab = _safe_float(bal.get("TOTAL_LIABILITIES"))
    equity = _safe_float(bal.get("TOTAL_PARENT_EQUITY"))
    if liab is None or equity is None or equity <= 0:
        return None
    return liab / equity


def _compute_gross_margin(ctx, symbol: str) -> float | None:
    """从最新年报指标读销售毛利率(XSMLL,百分比单位)。"""
    fin = ctx.get_financial_annual(symbol)
    if fin is None:
        return None
    return _safe_float(fin.get("XSMLL"))


def record_entry_baseline(ctx, symbol: str) -> dict[str, Any]:
    """记录入场时点的 D/E、毛利率、3 年均值支付率。

    任一字段不可达 → 该字段为 None,不阻塞其他字段记录。
    返回 dict 包含三个键:debt_equity / gross_margin / payout。
    """
    return {
        "debt_equity": _compute_debt_equity(ctx, symbol),
        "gross_margin": _compute_gross_margin(ctx, symbol),
        "payout": compute_payout_ratio_3y(ctx, symbol),
    }


# ---------- 7 条规则的具体检查 ----------


def _check_fcf_yield(ctx, symbol: str) -> bool:
    """规则 2:最新年报 FCF / 当前市值 < 5% → True。

    数据缺失 → False(不触发)。
    """
    cf = ctx.get_cashflow_annual(symbol)
    if cf is None:
        return False
    op = _safe_float(cf.get("NETCASH_OPERATE"))
    capex = _safe_float(cf.get("CONSTRUCT_LONG_ASSET"))
    if op is None:
        return False
    fcf = op - (capex if capex is not None else 0.0)

    fin = ctx.get_financial_annual(symbol)
    if fin is None:
        return False
    total_share = _safe_float(fin.get("TOTAL_SHARE"))
    if total_share is None or total_share <= 0:
        return False
    price = ctx.get_price(symbol)
    close = _safe_float(price.get("close")) if isinstance(price, dict) else None
    if close is None or close <= 0:
        return False
    market_cap = close * total_share
    if market_cap <= 0:
        return False
    return (fcf / market_cap) < FCF_YIELD_CRITICAL


def _check_debt_equity(ctx, symbol: str, baseline_de: float | None) -> bool:
    """规则 4:current D/E > max(baseline×1.5, 1.0) → True。

    baseline 缺失:仅用绝对兜底 1.0 阈值。
    current D/E 不可计算 → False。
    """
    current = _compute_debt_equity(ctx, symbol)
    if current is None:
        return False
    if baseline_de is None or baseline_de <= 0:
        threshold = DE_ABSOLUTE_CEILING
    else:
        threshold = max(baseline_de * DE_BASELINE_MULTIPLIER, DE_ABSOLUTE_CEILING)
    return current > threshold


def _check_revenue_yoy(ctx, symbol: str) -> bool:
    """规则 5:最新年报营收同比 < -20% → True。

    history 不足 2 期 / prior <= 0 → False。
    """
    history = ctx.get_income_annual_history(symbol, 2)
    if not history or len(history) < 2:
        return False
    latest = _safe_float(history[0].get("TOTAL_OPERATE_INCOME"))
    prior = _safe_float(history[1].get("TOTAL_OPERATE_INCOME"))
    if latest is None or prior is None or prior <= 0:
        return False
    yoy = (latest - prior) / prior
    return yoy < REVENUE_YOY_WARNING


def _check_gross_margin(ctx, symbol: str, baseline_gm: float | None) -> bool:
    """规则 6:current 毛利率 < baseline × 0.8 → True。

    baseline 缺失 / current 缺失 → False。
    """
    if baseline_gm is None or baseline_gm <= 0:
        return False
    current = _compute_gross_margin(ctx, symbol)
    if current is None:
        return False
    return current < baseline_gm * GROSS_MARGIN_BASELINE_RATIO


def _check_payout_decline(ctx, symbol: str, baseline_payout: float | None) -> bool:
    """规则 7:支付率较 baseline 相对降幅 > 30% → True。

    baseline 缺失 / current 缺失 / baseline <= 0 → False。
    """
    if baseline_payout is None or baseline_payout <= 0:
        return False
    current = compute_payout_ratio_3y(ctx, symbol)
    if current is None:
        return False
    decline = (baseline_payout - current) / baseline_payout
    return decline > PAYOUT_DECLINE_THRESHOLD


# ---------- 主入口 ----------


def cpa_fundamental_stop_loss(
    ctx, symbol: str, baseline: dict[str, Any] | None
) -> tuple[str | None, list[str]]:
    """检查 CPA 7 条基本面止损规则。

    返回:
      severity: "critical" | "warning" | None
        任一 critical 触发 → "critical"
        无 critical 但有 warning → "warning"
        全部未触发 → None
      reasons: 触发的规则 id 列表(rule_id 字符串,稳定排序方便日志/断言)

    baseline=None 等价于全字段为 None(规则 4/6/7 退化到无 baseline 行为)。
    """
    base = baseline or {}
    triggered_critical: list[str] = []
    triggered_warning: list[str] = []

    # critical 类
    if _is_net_cash_triggered(ctx, symbol):
        triggered_critical.append("net_cash_negative")
    if _check_fcf_yield(ctx, symbol):
        triggered_critical.append("fcf_yield_below_5pct")
    if _is_fcf_negative_2y_triggered(ctx, symbol):
        triggered_critical.append("fcf_negative_2y")

    # warning 类
    if _check_debt_equity(ctx, symbol, base.get("debt_equity")):
        triggered_warning.append("debt_equity_above_1.5x_baseline")
    if _check_revenue_yoy(ctx, symbol):
        triggered_warning.append("revenue_yoy_below_-20pct")
    if _check_gross_margin(ctx, symbol, base.get("gross_margin")):
        triggered_warning.append("gross_margin_below_0.8x_baseline")
    if _check_payout_decline(ctx, symbol, base.get("payout")):
        triggered_warning.append("payout_decline_above_30pct")

    reasons = triggered_critical + triggered_warning
    if triggered_critical:
        return ("critical", reasons)
    if triggered_warning:
        return ("warning", reasons)
    return (None, [])
