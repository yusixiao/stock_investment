"""LowValuationMultiFactorQuarterlyStrategy 集成测试。

聚焦 4 项增强:
1. 质量过滤(Stage 1.5)— 价值陷阱被剔除
2. ROE 阈值上调(默认 8.0)
3. 多因子复合 score 排序
4. 行业集中度上限(单行业 ≤ N)
"""

from __future__ import annotations

import pandas as pd

from tests.utils_test_helpers import MockContext

from services.backtest.strategies.experiments.low_valuation_multifactor import (
    low_valuation_multifactor_quarterly_strategy as mod,
)
from services.backtest.strategies.experiments.low_valuation_multifactor.low_valuation_multifactor_quarterly_strategy import (
    LowValuationMultiFactorQuarterlyStrategy,
)


def _patch_externals(monkeypatch, roe_map: dict[str, float]):
    """绕过年报 ROE 真实通路 + ST 真实通路。"""
    monkeypatch.setattr(
        mod.financial,
        "get_roe_annual_as_of_notice",
        lambda ctx, sym: roe_map.get(sym),
    )
    monkeypatch.setattr(mod, "_is_st_on", lambda sym, ds: False)


def _make_ctx(
    valuation: dict,
    history: dict | None = None,
    price: dict | None = None,
    dividend: dict | None = None,
) -> MockContext:
    return MockContext(
        valuation=valuation,
        history=history or {},
        price=price or {},
        dividend=dividend or {},
        current_date="2025-11-03",  # 命中默认 [5,9,11] 的 11 月调仓
    )


def _default_history(symbols: list[str]) -> dict:
    """120 根足够长的均匀历史(动量值 = 0,通过过滤)。"""
    return {sym: [{"close": 10.0}] * 121 for sym in symbols}


# ===== 基线:健康股票通过 =====
def test_healthy_stocks_pass(monkeypatch):
    valuation = {
        "A.SH": {"date": "2025-11-03", "pbMRQ": 0.6, "peTTM": 8.0},
        "B.SH": {"date": "2025-11-03", "pbMRQ": 0.7, "peTTM": 9.0},
    }
    ctx = _make_ctx(valuation, history=_default_history(["A.SH", "B.SH"]))
    _patch_externals(monkeypatch, {"A.SH": 12.0, "B.SH": 15.0})

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 0,  # 关掉行业限制
        }
    )
    selected = strat.screen(ctx, ["A.SH", "B.SH"])
    assert set(selected) == {"A.SH", "B.SH"}


# ===== Stage 1.5 质量过滤 =====
def test_quality_filter_rejects_negative_cfo(monkeypatch):
    valuation = {
        "BAD.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 8.0},
        "GOOD.SH": {"date": "2025-11-03", "pbMRQ": 0.6, "peTTM": 9.0},
    }
    ctx = _make_ctx(valuation, history=_default_history(["BAD.SH", "GOOD.SH"]))
    # BAD.SH:CFO < 0(非金融业)→ 被质量过滤剔除
    ctx.set_balance({"BAD.SH": {"INDUSTRY_NAME": "钢铁"}})
    ctx.set_cashflow_history({"BAD.SH": [{"NETCASH_OPERATE": -100.0}]})
    _patch_externals(monkeypatch, {"BAD.SH": 12.0, "GOOD.SH": 15.0})

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 0,
        }
    )
    selected = strat.screen(ctx, ["BAD.SH", "GOOD.SH"])
    assert "BAD.SH" not in selected
    assert "GOOD.SH" in selected


def test_quality_filter_rejects_high_debt_ratio(monkeypatch):
    valuation = {
        "DEBT.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 8.0},
        "GOOD.SH": {"date": "2025-11-03", "pbMRQ": 0.6, "peTTM": 9.0},
    }
    ctx = _make_ctx(valuation, history=_default_history(["DEBT.SH", "GOOD.SH"]))
    ctx.set_balance(
        {
            "DEBT.SH": {
                "INDUSTRY_NAME": "建筑",
                "TOTAL_LIABILITIES": 85.0,
                "TOTAL_ASSETS": 100.0,
            }
        }
    )
    _patch_externals(monkeypatch, {"DEBT.SH": 12.0, "GOOD.SH": 15.0})

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 0,
        }
    )
    selected = strat.screen(ctx, ["DEBT.SH", "GOOD.SH"])
    assert "DEBT.SH" not in selected


def test_quality_filter_exempts_bank(monkeypatch):
    """银行业即使负债率 95% 也应通过质量过滤。"""
    valuation = {
        "BANK.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 8.0},
    }
    ctx = _make_ctx(valuation, history=_default_history(["BANK.SH"]))
    ctx.set_balance(
        {
            "BANK.SH": {
                "INDUSTRY_NAME": "股份制银行",
                "TOTAL_LIABILITIES": 95.0,
                "TOTAL_ASSETS": 100.0,
            }
        }
    )
    ctx.set_cashflow_history({"BANK.SH": [{"NETCASH_OPERATE": -50.0}]})
    _patch_externals(monkeypatch, {"BANK.SH": 12.0})

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 0,
        }
    )
    selected = strat.screen(ctx, ["BANK.SH"])
    assert "BANK.SH" in selected


# ===== ROE 阈值上调到 8 =====
def test_roe_threshold_default_8(monkeypatch):
    valuation = {
        "LOW.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 8.0},
        "HIGH.SH": {"date": "2025-11-03", "pbMRQ": 0.6, "peTTM": 9.0},
    }
    ctx = _make_ctx(valuation, history=_default_history(["LOW.SH", "HIGH.SH"]))
    # LOW.SH: ROE 6%(不达 8% 默认阈值)→ 剔除
    _patch_externals(monkeypatch, {"LOW.SH": 6.0, "HIGH.SH": 12.0})

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 0,
        }
    )
    selected = strat.screen(ctx, ["LOW.SH", "HIGH.SH"])
    assert "LOW.SH" not in selected
    assert "HIGH.SH" in selected


# ===== 多因子 score 排序 =====
def test_multifactor_score_orders_by_composite(monkeypatch):
    """三只股票:A 综合最优、B 中、C 最差。top_n=2 应取 A 和 B。"""
    valuation = {
        "A.SH": {"date": "2025-11-03", "pbMRQ": 0.3, "peTTM": 5.0},  # 最低估
        "B.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 8.0},
        "C.SH": {"date": "2025-11-03", "pbMRQ": 0.9, "peTTM": 25.0},  # 最贵
    }
    history = _default_history(["A.SH", "B.SH", "C.SH"])
    # ROE 也呈递减
    _patch_externals(monkeypatch, {"A.SH": 25.0, "B.SH": 15.0, "C.SH": 9.0})
    ctx = _make_ctx(valuation, history=history)

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 0,
            "top_n": 2,
        }
    )
    selected = strat.screen(ctx, ["A.SH", "B.SH", "C.SH"])
    assert selected == ["A.SH", "B.SH"]
    # 验证 Score 因子已记录
    assert "Score" in ctx.get_factors("A.SH")


# ===== 行业集中度上限 =====
def test_industry_cap_limits_per_industry(monkeypatch):
    """4 只银行 + 1 只白酒,max_per_industry=2 → 银行只取 2 只。"""
    symbols = ["BK1.SH", "BK2.SH", "BK3.SH", "BK4.SH", "BAIJIU.SH"]
    valuation = {
        "BK1.SH": {"date": "2025-11-03", "pbMRQ": 0.3, "peTTM": 5.0},
        "BK2.SH": {"date": "2025-11-03", "pbMRQ": 0.4, "peTTM": 6.0},
        "BK3.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 7.0},
        "BK4.SH": {"date": "2025-11-03", "pbMRQ": 0.6, "peTTM": 8.0},
        "BAIJIU.SH": {"date": "2025-11-03", "pbMRQ": 0.9, "peTTM": 25.0},
    }
    history = _default_history(symbols)
    ctx = _make_ctx(valuation, history=history)
    ctx.set_balance(
        {
            "BK1.SH": {"INDUSTRY_NAME": "股份制银行"},
            "BK2.SH": {"INDUSTRY_NAME": "股份制银行"},
            "BK3.SH": {"INDUSTRY_NAME": "股份制银行"},
            "BK4.SH": {"INDUSTRY_NAME": "股份制银行"},
            "BAIJIU.SH": {"INDUSTRY_NAME": "白酒"},
        }
    )
    _patch_externals(
        monkeypatch,
        {
            "BK1.SH": 14.0,
            "BK2.SH": 13.0,
            "BK3.SH": 12.0,
            "BK4.SH": 11.0,
            "BAIJIU.SH": 25.0,
        },
    )
    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 2,
            "top_n": 5,
        }
    )
    selected = strat.screen(ctx, symbols)
    # 银行最多 2 只 + 白酒 1 只 = 3 只
    bank_count = sum(1 for s in selected if s.startswith("BK"))
    assert bank_count == 2
    assert "BAIJIU.SH" in selected
    assert len(selected) == 3


# ===== 调仓月份限制 =====
def test_screen_skips_non_rebalance_month(monkeypatch):
    valuation = {"A.SH": {"date": "2025-06-03", "pbMRQ": 0.5, "peTTM": 8.0}}
    ctx = MockContext(
        valuation=valuation,
        history=_default_history(["A.SH"]),
        current_date="2025-06-03",  # 6 月不是 [5,9,11]
    )
    _patch_externals(monkeypatch, {"A.SH": 12.0})
    strat = LowValuationMultiFactorQuarterlyStrategy()
    assert strat.screen(ctx, ["A.SH"]) == []


# ===== 空候选返回空列表 + 标记调仓 =====
def test_empty_after_filter_returns_empty(monkeypatch):
    """所有股票都被 ROE 过滤 → 空选股,但调仓标记应置位(便于 on_sell 清仓)。"""
    valuation = {
        "A.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 8.0},
    }
    ctx = _make_ctx(valuation, history=_default_history(["A.SH"]))
    _patch_externals(monkeypatch, {"A.SH": 3.0})  # 不达 8% 阈值

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={"rebalance_months": [11], "momentum_drop_pct": 0.0}
    )
    selected = strat.screen(ctx, ["A.SH"])
    assert selected == []
    assert strat._rebalance_pending is True


# ===== NaN PB 防御沿用 =====
def test_nan_pb_rejected(monkeypatch):
    valuation = {
        "BAD.HK": {"date": "2025-11-03", "pbMRQ": float("nan"), "peTTM": 5.0},
        "GOOD.HK": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 5.0},
    }
    ctx = _make_ctx(valuation, history=_default_history(["BAD.HK", "GOOD.HK"]))
    _patch_externals(monkeypatch, {"BAD.HK": 90.0, "GOOD.HK": 10.0})

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 0,
        }
    )
    selected = strat.screen(ctx, ["BAD.HK", "GOOD.HK"])
    assert "BAD.HK" not in selected
    assert "GOOD.HK" in selected


# ===== on_sell + on_buy 调仓 =====
def test_on_sell_clears_non_target():
    strat = LowValuationMultiFactorQuarterlyStrategy()
    strat._target_holdings = ["A.SH"]
    strat._rebalance_pending = True

    ctx = MockContext(
        price={
            "OLD.SH": {"daily": {"close": 10.0}},
        }
    )
    ctx.set_positions({"OLD.SH": 1000, "A.SH": 500})
    strat.on_sell(ctx)

    # OLD.SH 应被全清(-1000),A.SH 保留
    assert ("OLD.SH", -1000) in ctx.orders
    assert all(sym != "A.SH" for sym, _ in ctx.orders)


def test_on_buy_equal_weight():
    strat = LowValuationMultiFactorQuarterlyStrategy()
    strat._target_holdings = ["A.SH", "B.SH", "C.SH", "D.SH"]
    strat._rebalance_pending = True

    ctx = MockContext()
    strat.on_buy(ctx)

    # 4 只 → 每只 25%
    assert len(ctx.target_pct_orders) == 4
    for _, pct in ctx.target_pct_orders:
        assert abs(pct - 0.25) < 1e-9
    assert strat._rebalance_pending is False


# ===== 逆动量加分 =====
def _build_history_with_momentum(symbol: str, total_return: float, n: int = 121):
    """构造 n 根 daily bar,使首尾收益率 = total_return(线性插值近似)。"""
    start = 10.0
    end = start * (1.0 + total_return)
    closes = [start + (end - start) * i / (n - 1) for i in range(n)]
    return [{"close": c} for c in closes]


def test_neg_momentum_boosts_falling_stocks(monkeypatch):
    """开启逆动量加分(其他因子权重清零)→ 跌幅最大的股票排第一。"""
    valuation = {
        "DROP.SH": {"date": "2025-11-03", "pbMRQ": 0.7, "peTTM": 9.0},
        "FLAT.SH": {"date": "2025-11-03", "pbMRQ": 0.7, "peTTM": 9.0},
        "UP.SH": {"date": "2025-11-03", "pbMRQ": 0.7, "peTTM": 9.0},
    }
    history = {
        "DROP.SH": _build_history_with_momentum("DROP.SH", -0.3),  # 跌 30%
        "FLAT.SH": _build_history_with_momentum("FLAT.SH", 0.0),
        "UP.SH": _build_history_with_momentum("UP.SH", 0.3),  # 涨 30%
    }
    ctx = _make_ctx(valuation, history=history)
    _patch_externals(monkeypatch, {"DROP.SH": 12.0, "FLAT.SH": 12.0, "UP.SH": 12.0})

    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,  # 关掉动量分位剔除
            "max_per_industry": 0,
            "top_n": 1,
            # 关闭其他因子,只留逆动量
            "score_weight_inv_pb": 0.0,
            "score_weight_roe": 0.0,
            "score_weight_div_yield": 0.0,
            "score_weight_inv_pe": 0.0,
            "score_weight_neg_momentum": 1.0,
            "neg_momentum_lookback_days": 60,
        }
    )
    selected = strat.screen(ctx, ["DROP.SH", "FLAT.SH", "UP.SH"])
    assert selected == ["DROP.SH"]
    # NegMomentum 因子应被记录
    assert "NegMomentum" in ctx.get_factors("DROP.SH")


def test_neg_momentum_weight_zero_skips_computation(monkeypatch):
    """权重 = 0 时不应记录 NegMomentum 因子(性能优化路径)。"""
    valuation = {
        "A.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 8.0},
    }
    ctx = _make_ctx(valuation, history=_default_history(["A.SH"]))
    _patch_externals(monkeypatch, {"A.SH": 12.0})
    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={
            "rebalance_months": [11],
            "momentum_drop_pct": 0.0,
            "max_per_industry": 0,
            "score_weight_neg_momentum": 0.0,  # 默认值
        }
    )
    strat.screen(ctx, ["A.SH"])
    assert "NegMomentum" not in ctx.get_factors("A.SH")


# ===== inv_vol 仓位加权 =====
def _history_with_volatility(seed: int, n: int = 61, sigma: float = 0.01):
    """生成 n 根 bar,daily-return 服从 N(0, sigma^2)(seeded 重现)。"""
    import numpy as np

    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, sigma, n - 1)
    closes = [10.0]
    for r in rets:
        closes.append(closes[-1] * (1.0 + r))
    return [{"close": c} for c in closes]


def test_on_buy_inv_vol_low_sigma_gets_more():
    """三只标的:LOW(σ=0.005), MID(σ=0.02), HIGH(σ=0.05) → LOW 权重最大。"""
    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={"position_weighting": "inv_vol", "vol_lookback_days": 60}
    )
    strat._target_holdings = ["LOW.SH", "MID.SH", "HIGH.SH"]
    strat._rebalance_pending = True

    ctx = MockContext(
        history={
            "LOW.SH": _history_with_volatility(seed=1, sigma=0.005),
            "MID.SH": _history_with_volatility(seed=2, sigma=0.02),
            "HIGH.SH": _history_with_volatility(seed=3, sigma=0.05),
        }
    )
    strat.on_buy(ctx)

    weights = dict(ctx.target_pct_orders)
    assert len(weights) == 3
    # LOW 权重应最大,HIGH 最小
    assert weights["LOW.SH"] > weights["MID.SH"] > weights["HIGH.SH"]
    # 总权重 ≈ 1.0
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_on_buy_inv_vol_falls_back_when_no_history():
    """所有标的都无 history → 全部回退等权(1/N)。"""
    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={"position_weighting": "inv_vol", "vol_lookback_days": 60}
    )
    strat._target_holdings = ["A.SH", "B.SH"]
    strat._rebalance_pending = True

    ctx = MockContext()  # 无 history
    strat.on_buy(ctx)

    assert len(ctx.target_pct_orders) == 2
    for _, pct in ctx.target_pct_orders:
        assert abs(pct - 0.5) < 1e-9


def test_on_buy_inv_vol_partial_history_uses_median_fallback():
    """部分标的无 history → 用中位数 σ 兜底,仍能产出归一化权重。"""
    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={"position_weighting": "inv_vol", "vol_lookback_days": 60}
    )
    strat._target_holdings = ["A.SH", "B.SH", "MISSING.SH"]
    strat._rebalance_pending = True

    ctx = MockContext(
        history={
            "A.SH": _history_with_volatility(seed=1, sigma=0.01),
            "B.SH": _history_with_volatility(seed=2, sigma=0.02),
            # MISSING.SH 无 history
        }
    )
    strat.on_buy(ctx)

    weights = dict(ctx.target_pct_orders)
    assert len(weights) == 3
    # 总权重 ≈ 1.0
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    # MISSING 用中位数 σ 兜底,权重应为正
    assert weights["MISSING.SH"] > 0


# ===== 止损 / 止盈 =====
def _make_position_ctx(
    positions: dict[str, tuple[int, float]], prices: dict[str, float]
):
    """positions: {sym: (shares, cost)};prices: {sym: close}。"""
    from types import SimpleNamespace

    ctx = MockContext(price={sym: {"daily": {"close": p}} for sym, p in prices.items()})
    ctx._positions = {
        sym: SimpleNamespace(shares=n, cost=c, buy_date="2024-01-01")
        for sym, (n, c) in positions.items()
    }
    return ctx


def test_stop_loss_triggers_when_pnl_below_threshold():
    """个股跌幅 ≥ stop_loss_pct → 清仓。"""
    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={"stop_loss_pct": 0.20}
    )
    strat._rebalance_pending = False  # 非调仓日

    ctx = _make_position_ctx(
        positions={
            "DROP.SH": (1000, 10.0),  # 现价 7.5 = -25%,触发止损
            "OK.SH": (500, 10.0),  # 现价 9.0 = -10%,不触发
        },
        prices={"DROP.SH": 7.5, "OK.SH": 9.0},
    )
    strat.on_sell(ctx)

    assert ("DROP.SH", -1000) in ctx.orders
    assert all(sym != "OK.SH" for sym, _ in ctx.orders)


def test_take_profit_triggers_when_pnl_above_threshold():
    """个股涨幅 ≥ take_profit_pct → 清仓。"""
    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={"take_profit_pct": 0.50}
    )
    strat._rebalance_pending = False

    ctx = _make_position_ctx(
        positions={
            "MOON.SH": (1000, 10.0),  # 现价 16 = +60%,触发止盈
            "OK.SH": (500, 10.0),  # 现价 13 = +30%,不触发
        },
        prices={"MOON.SH": 16.0, "OK.SH": 13.0},
    )
    strat.on_sell(ctx)

    assert ("MOON.SH", -1000) in ctx.orders
    assert all(sym != "OK.SH" for sym, _ in ctx.orders)


def test_sl_tp_disabled_by_default():
    """默认 sl=0/tp=0 → 不触发任何止损止盈卖出。"""
    strat = LowValuationMultiFactorQuarterlyStrategy()
    strat._rebalance_pending = False

    ctx = _make_position_ctx(
        positions={"DROP.SH": (1000, 10.0)},
        prices={"DROP.SH": 5.0},  # -50%
    )
    strat.on_sell(ctx)
    assert ctx.orders == []


def test_sl_removes_from_target_holdings():
    """止损卖出后从 _target_holdings 移除,防止 on_buy 当日买回。"""
    strat = LowValuationMultiFactorQuarterlyStrategy(
        param_overrides={"stop_loss_pct": 0.10}
    )
    strat._target_holdings = ["DROP.SH", "OK.SH"]
    strat._rebalance_pending = True

    ctx = _make_position_ctx(
        positions={"DROP.SH": (1000, 10.0)},
        prices={"DROP.SH": 8.5, "OK.SH": 10.0},  # DROP -15% 触发
    )
    strat.on_sell(ctx)

    assert "DROP.SH" not in strat._target_holdings
    assert "OK.SH" in strat._target_holdings


def test_on_buy_default_equal_when_position_weighting_equal():
    """默认 equal → 即使 inv_vol 数据可用也走等权。"""
    strat = LowValuationMultiFactorQuarterlyStrategy()  # 默认 equal
    strat._target_holdings = ["A.SH", "B.SH"]
    strat._rebalance_pending = True

    ctx = MockContext(
        history={
            "A.SH": _history_with_volatility(seed=1, sigma=0.005),
            "B.SH": _history_with_volatility(seed=2, sigma=0.05),
        }
    )
    strat.on_buy(ctx)

    weights = dict(ctx.target_pct_orders)
    assert abs(weights["A.SH"] - 0.5) < 1e-9
    assert abs(weights["B.SH"] - 0.5) < 1e-9
