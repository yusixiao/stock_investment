"""MarketCapWeightedBatchBuyer L3 tier 加权扩展单测。

验证:
- tier_weights=None(默认):行为完全等同原逻辑(向后兼容)
- tier_weights 启用时:effective_mv = mv × tier_weights[tier]
- factor 缺失 / tier 不在字典 → 权重 1.0(降级保守)
"""

from __future__ import annotations

from tests.utils_test_helpers import MockContext

from strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


def _ctx_two_symbols_equal_mv(cash=1_000_000):
    """A 和 B 市值相同(都是 6e11),只让 tier 影响分配。"""
    return MockContext(
        financial={
            "A": {"TOTAL_SHARE": 5e10},
            "B": {"TOTAL_SHARE": 5e10},
        },
        price={
            "A": {
                "daily": {"close": 12.0},
                "weekly": {"open": 10.0, "close": 12.0},
            },
            "B": {
                "daily": {"close": 12.0},
                "weekly": {"open": 10.0, "close": 12.0},
            },
        },
        target_symbols=["A", "B"],
        new_symbols=["A", "B"],
        available_cash=cash,
        current_date="2024-01-01",
    )


def test_no_tier_weights_default_is_market_cap_only():
    """tier_weights=None → 即便 ctx 有 position_tier factor,也按市值平分。"""
    ctx = _ctx_two_symbols_equal_mv()
    ctx.record_factor("A", "position_tier", "full")
    ctx.record_factor("B", "position_tier", "half")
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    # 市值相同 → 50/50
    assert abs(plan_a["weekly_amount"] - plan_b["weekly_amount"]) < 1.0


def test_tier_weights_full_double_half():
    """tier_weights={'full':2,'half':1} + 同市值 → A 占 2/3,B 占 1/3。"""
    ctx = _ctx_two_symbols_equal_mv()
    ctx.record_factor("A", "position_tier", "full")
    ctx.record_factor("B", "position_tier", "half")
    buyer = MarketCapWeightedBatchBuyer(
        buy_weeks=8, tier_weights={"full": 2.0, "half": 1.0}
    )
    buyer.step(ctx)
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    expected_a = 1_000_000 * (2.0 / 3.0) / 8
    expected_b = 1_000_000 * (1.0 / 3.0) / 8
    assert abs(plan_a["weekly_amount"] - expected_a) < 1.0
    assert abs(plan_b["weekly_amount"] - expected_b) < 1.0


def test_tier_weights_missing_factor_falls_back_to_one():
    """部分 symbol 缺 position_tier factor → 用权重 1.0 (中性)。"""
    ctx = _ctx_two_symbols_equal_mv()
    ctx.record_factor("A", "position_tier", "full")
    # B 不打 tier
    buyer = MarketCapWeightedBatchBuyer(
        buy_weeks=8, tier_weights={"full": 2.0, "half": 1.0}
    )
    buyer.step(ctx)
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    # A 权重 2,B fallback 1 → A 占 2/3
    expected_a = 1_000_000 * (2.0 / 3.0) / 8
    expected_b = 1_000_000 * (1.0 / 3.0) / 8
    assert abs(plan_a["weekly_amount"] - expected_a) < 1.0
    assert abs(plan_b["weekly_amount"] - expected_b) < 1.0


def test_tier_weights_unknown_tier_falls_back_to_one():
    """tier 字符串不在 weights 字典 → 权重 1.0。"""
    ctx = _ctx_two_symbols_equal_mv()
    ctx.record_factor("A", "position_tier", "full")
    ctx.record_factor("B", "position_tier", "observe")  # 不在字典
    buyer = MarketCapWeightedBatchBuyer(
        buy_weeks=8, tier_weights={"full": 2.0, "half": 1.0}
    )
    buyer.step(ctx)
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    # A 权重 2,B fallback 1 → A 占 2/3
    expected_a = 1_000_000 * (2.0 / 3.0) / 8
    assert abs(plan_a["weekly_amount"] - expected_a) < 1.0


def test_tier_weights_combined_with_market_cap():
    """同 tier 不同市值时,仍按市值进一步细分。"""
    ctx = MockContext(
        financial={
            "A": {"TOTAL_SHARE": 5e10},  # mv = 6e11
            "B": {"TOTAL_SHARE": 1e10},  # mv = 1.2e11
        },
        price={
            "A": {
                "daily": {"close": 12.0},
                "weekly": {"open": 10.0, "close": 12.0},
            },
            "B": {
                "daily": {"close": 12.0},
                "weekly": {"open": 10.0, "close": 12.0},
            },
        },
        target_symbols=["A", "B"],
        new_symbols=["A", "B"],
        available_cash=1_000_000,
        current_date="2024-01-01",
    )
    ctx.record_factor("A", "position_tier", "half")  # 1.0
    ctx.record_factor("B", "position_tier", "full")  # 2.0
    buyer = MarketCapWeightedBatchBuyer(
        buy_weeks=8, tier_weights={"full": 2.0, "half": 1.0}
    )
    buyer.step(ctx)
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    # eff_a = 6e11 * 1.0 = 6e11; eff_b = 1.2e11 * 2.0 = 2.4e11
    # ratio_a = 6/8.4 ≈ 0.714; ratio_b = 2.4/8.4 ≈ 0.286
    total_eff = 6e11 + 2.4e11
    expected_a = 1_000_000 * (6e11 / total_eff) / 8
    expected_b = 1_000_000 * (2.4e11 / total_eff) / 8
    assert abs(plan_a["weekly_amount"] - expected_a) < 1.0
    assert abs(plan_b["weekly_amount"] - expected_b) < 1.0


def test_tier_weights_zero_weight_excludes_symbol():
    """权重 0 的 tier → effective_mv=0 → 不分配资金(允许策略级软排除)。"""
    ctx = _ctx_two_symbols_equal_mv()
    ctx.record_factor("A", "position_tier", "full")
    ctx.record_factor("B", "position_tier", "observe")
    buyer = MarketCapWeightedBatchBuyer(
        buy_weeks=8,
        tier_weights={"full": 2.0, "half": 1.0, "observe": 0.0},
    )
    buyer.step(ctx)
    # B 应被排除(weekly_amount=0 也应不创建计划,或至少不下单)
    if "B" in buyer._buy_plans:
        assert buyer._buy_plans["B"]["weekly_amount"] == 0.0
    plan_a = buyer._buy_plans["A"]
    # A 拿全部资金
    assert abs(plan_a["weekly_amount"] - 1_000_000 / 8) < 1.0
