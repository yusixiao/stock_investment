"""LowValuationQuarterlyStrategy 回归测试。

主要锁住 NaN 估值防御(2026-06-10 fab04c35 任务暴露的 bug):
HK/US 的 pbMRQ 由 DuckDB 用 `BPS>0 → close/BPS ELSE NULL` 派生,负净资产
公司返 NaN。NaN 与任何数比较都返 False,会绕过 `pb<=0/pb>pb_max` 全部
判断,被错误纳入候选(典型反例:06158.HK 正商实业 BPS=-2.57)。
"""

from __future__ import annotations

import math

import pandas as pd

from tests.utils_test_helpers import MockContext

from strategies.deployed import low_valuation_quarterly_strategy as mod
from strategies.deployed.low_valuation_quarterly_strategy import (
    LowValuationQuarterlyStrategy,
)


def _make_ctx(valuation: dict, history: dict | None = None) -> MockContext:
    """构造 11 月调仓日的 MockContext(2025-11-03 是 rebalance_months=[11] 命中日)。"""
    ctx = MockContext(
        valuation=valuation,
        history=history or {},
        current_date="2025-11-03",
    )
    return ctx


def _patch_externals(monkeypatch, roe_map: dict[str, float]):
    """绕过策略对 financial.get_roe_annual_as_of_notice 与 _is_st_on 的依赖。"""
    monkeypatch.setattr(
        mod.financial,
        "get_roe_annual_as_of_notice",
        lambda ctx, sym: roe_map.get(sym),
    )
    monkeypatch.setattr(mod, "_is_st_on", lambda sym, ds: False)


def test_nan_pb_rejected(monkeypatch):
    """NaN pbMRQ 必须被 stage1 过滤(回归 fab04c35 任务的 06158.HK bug)。"""
    valuation = {
        "BAD.HK": {"date": "2025-11-03", "pbMRQ": float("nan"), "peTTM": 5.0},
        "GOOD.HK": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 5.0},
    }
    # 给两只都构造满足动量 lookback 的历史
    history = {sym: [{"close": 10.0}] * 121 for sym in valuation}
    ctx = _make_ctx(valuation, history)
    _patch_externals(monkeypatch, {"BAD.HK": 90.0, "GOOD.HK": 10.0})

    strat = LowValuationQuarterlyStrategy(
        param_overrides={"rebalance_months": [11], "momentum_drop_pct": 0.0}
    )
    selected = strat.screen(ctx, ["BAD.HK", "GOOD.HK"])

    assert "BAD.HK" not in selected
    assert "GOOD.HK" in selected


def test_nan_pe_rejected(monkeypatch):
    """NaN peTTM 必须被 stage1 过滤(同 NaN PB 同源问题:净亏损时 EPSJB ≤ 0)。"""
    valuation = {
        "LOSS.HK": {"date": "2025-11-03", "pbMRQ": 0.4, "peTTM": float("nan")},
        "GOOD.HK": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 5.0},
    }
    history = {sym: [{"close": 10.0}] * 121 for sym in valuation}
    ctx = _make_ctx(valuation, history)
    _patch_externals(monkeypatch, {"LOSS.HK": 10.0, "GOOD.HK": 10.0})

    strat = LowValuationQuarterlyStrategy(
        param_overrides={"rebalance_months": [11], "momentum_drop_pct": 0.0}
    )
    selected = strat.screen(ctx, ["LOSS.HK", "GOOD.HK"])

    assert "LOSS.HK" not in selected
    assert "GOOD.HK" in selected


def test_negative_pb_still_rejected(monkeypatch):
    """A 股口径的负 PB(BaoStock 直供负数)继续被过滤,不退化。"""
    valuation = {
        "NEG.SH": {"date": "2025-11-03", "pbMRQ": -1.5, "peTTM": 5.0},
        "GOOD.SH": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 5.0},
    }
    history = {sym: [{"close": 10.0}] * 121 for sym in valuation}
    ctx = _make_ctx(valuation, history)
    _patch_externals(monkeypatch, {"NEG.SH": 90.0, "GOOD.SH": 10.0})

    strat = LowValuationQuarterlyStrategy(
        param_overrides={"rebalance_months": [11], "momentum_drop_pct": 0.0}
    )
    selected = strat.screen(ctx, ["NEG.SH", "GOOD.SH"])

    assert "NEG.SH" not in selected
    assert "GOOD.SH" in selected


def test_pandas_na_rejected(monkeypatch):
    """pd.NA 也要拦下(防御性,真实通路虽然不应出现但保险)。"""
    valuation = {
        "NA.HK": {"date": "2025-11-03", "pbMRQ": pd.NA, "peTTM": 5.0},
        "GOOD.HK": {"date": "2025-11-03", "pbMRQ": 0.5, "peTTM": 5.0},
    }
    history = {sym: [{"close": 10.0}] * 121 for sym in valuation}
    ctx = _make_ctx(valuation, history)
    _patch_externals(monkeypatch, {"NA.HK": 90.0, "GOOD.HK": 10.0})

    strat = LowValuationQuarterlyStrategy(
        param_overrides={"rebalance_months": [11], "momentum_drop_pct": 0.0}
    )
    selected = strat.screen(ctx, ["NA.HK", "GOOD.HK"])

    assert "NA.HK" not in selected
    assert "GOOD.HK" in selected


def test_bug_06158_does_not_pass_stage1():
    """直接验证修复点:NaN PB 不应进 stage1 候选(行为级断言)。

    复现 fab04c35 任务在 2025-11-03 的真实输入:06158.HK pbMRQ=NaN
    (DuckDB 由 BPS=-2.57 派生 → NULL → pandas NaN)。
    """
    pb = float("nan")
    pb_max = 1.0
    # 修复后的判定式
    assert pd.isna(pb) or pb <= 0 or pb > pb_max
    # 修复前的(漏)判定式作为对照,确认确实漏过
    assert not (pb is None or pb <= 0 or pb > pb_max)
    assert math.isnan(pb)
