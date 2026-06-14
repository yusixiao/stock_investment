"""CpaTierBatchBuyer 单测。

CPA 原口径:single-stock 仓位 = max_per_stock_pct × TIER_PCT[tier],
分 N 周等额爬坡,通过 ctx.order_target_percent 下单。
"""

from __future__ import annotations

import pytest

from tests.utils_test_helpers import MockContext

from services.backtest.strategies.utils.composite.cpa_tier_batch_buyer import CpaTierBatchBuyer


def _approx_orders(
    orders: list[tuple[str, float]], expected: list[tuple[str, float]]
) -> bool:
    """断言 [(sym, pct), ...] 列表近似相等(浮点容忍 1e-9)。"""
    if len(orders) != len(expected):
        return False
    for (s1, p1), (s2, p2) in zip(orders, expected):
        if s1 != s2:
            return False
        if p1 != pytest.approx(p2, abs=1e-9):
            return False
    return True


def _ctx_with_tier(target_symbols: list[str], new_symbols: list[str], date: str):
    ctx = MockContext(
        target_symbols=target_symbols,
        new_symbols=new_symbols,
        current_date=date,
    )
    return ctx


# ---------- 分配阶段 ----------


def test_full_tier_allocates_max_pct():
    """tier=full → target_pct = max_per_stock_pct × 1.0(20%)。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "full")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx)
    # 第 1 周:目标 = 20% × 1/4 = 5%
    assert _approx_orders(ctx.target_pct_orders, [("A", 0.05)])


def test_p70_tier_allocates_70pct():
    """tier=p70 → target_pct = 20% × 0.7 = 14%。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "p70")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx)
    # 第 1 周:14% × 1/4 = 3.5%
    assert _approx_orders(ctx.target_pct_orders, [("A", 0.035)])


def test_observe_tier_no_allocation():
    """tier=observe → 不建立 plan,无下单。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "observe")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx)
    assert ctx.target_pct_orders == []


def test_skip_tier_no_allocation():
    """tier=skip → 不建立 plan。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "skip")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx)
    assert ctx.target_pct_orders == []


def test_missing_tier_no_allocation():
    """无 position_tier factor → 不分配(保守)。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx)
    assert ctx.target_pct_orders == []


# ---------- 分批爬坡 ----------


def test_4_weeks_progressive_buildup():
    """4 周分批,目标 20% → 5/10/15/20% 逐周累积。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "full")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx)  # week 1
    # 模拟第 2 周(1 周后)
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"
    buyer.step(ctx)
    # 第 3 周
    ctx.current_date = "2024-01-15"
    buyer.step(ctx)
    # 第 4 周
    ctx.current_date = "2024-01-22"
    buyer.step(ctx)

    expected = [
        ("A", 0.05),  # week 1: 20% × 1/4
        ("A", 0.10),  # week 2: 20% × 2/4
        ("A", 0.15),  # week 3
        ("A", 0.20),  # week 4: 满仓
    ]
    assert _approx_orders(ctx.target_pct_orders, expected)


def test_no_double_buy_in_same_week():
    """同一周内多次 step 不重复下单。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "full")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx)  # week 1, 1 单
    ctx.new_symbols = []
    buyer.step(ctx)  # 同周再调,不下单
    assert len(ctx.target_pct_orders) == 1


def test_plan_finished_after_buy_weeks():
    """完成 buy_weeks 周后,plan 自动清理。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "full")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=2)
    buyer.step(ctx)  # week 1
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"
    buyer.step(ctx)  # week 2,完成
    # 第 3 周再调,plan 已清空,不下单
    ctx.current_date = "2024-01-15"
    buyer.step(ctx)
    assert len(ctx.target_pct_orders) == 2  # 仅 2 周
    assert "A" not in buyer._buy_plans


# ---------- 持仓上限 ----------


def test_max_holdings_limits_new_allocations():
    """max_holdings=2 + 已持仓 1 + 新命中 3 → 仅分配 1 个新计划。"""
    ctx = _ctx_with_tier(["X", "A", "B", "C"], ["A", "B", "C"], "2024-01-01")
    ctx.set_positions({"X": 100})
    for s in ("A", "B", "C"):
        ctx.record_factor(s, "position_tier", "full")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx, max_holdings=2)
    # 持仓 X(1)+ 新建 1 个 plan = 2 → 只能 quota=1
    assert len(buyer._buy_plans) == 1
    # A 优先(列表顺序)
    assert "A" in buyer._buy_plans


def test_max_holdings_blocks_when_full():
    """已持仓 = max_holdings → 不分配新计划。"""
    ctx = _ctx_with_tier(["X", "Y", "A"], ["A"], "2024-01-01")
    ctx.set_positions({"X": 100, "Y": 100})
    ctx.record_factor("A", "position_tier", "full")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx, max_holdings=2)
    assert "A" not in buyer._buy_plans
    assert ctx.target_pct_orders == []


# ---------- 卖出后停止 ----------


def test_symbol_removed_from_target_stops_buying():
    """seller 把 sym 移出 target_symbols → buyer 停止后续买入。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "full")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    buyer.step(ctx)  # week 1 买
    # seller 强行清仓
    ctx.target_symbols.remove("A")
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"
    buyer.step(ctx)
    # plan 被清理
    assert "A" not in buyer._buy_plans
    # 仅第 1 周下了单
    assert len(ctx.target_pct_orders) == 1


# ---------- 自定义参数 ----------


def test_custom_tier_pct_map():
    """tier_pct_map 可覆盖默认。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "p70")
    buyer = CpaTierBatchBuyer(
        max_per_stock_pct=0.20,
        buy_weeks=4,
        tier_pct_map={"full": 1.0, "p70": 0.5, "observe": 0.0, "skip": 0.0},
    )
    buyer.step(ctx)
    # p70 改成 50% → target = 20% × 0.5 = 10%,week1 = 10%/4 = 2.5%
    assert _approx_orders(ctx.target_pct_orders, [("A", 0.025)])


def test_max_per_stock_pct_param():
    """max_per_stock_pct 可调,如改 30%。"""
    ctx = _ctx_with_tier(["A"], ["A"], "2024-01-01")
    ctx.record_factor("A", "position_tier", "full")
    buyer = CpaTierBatchBuyer(max_per_stock_pct=0.30, buy_weeks=3)
    buyer.step(ctx)
    # 30% × 1.0 / 3 = 10%
    assert _approx_orders(ctx.target_pct_orders, [("A", 0.10)])
