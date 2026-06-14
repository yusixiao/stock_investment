from tests.utils_test_helpers import MockContext
from services.backtest.strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


def _ctx_with_two_new_symbols(cash=1_000_000):
    # English schema(2026-05-21):total_mv 派生自 close × TOTAL_SHARE
    # A: 12 × 5e10 = 6e11;B: 22 × ~1.818e10 ≈ 4e11
    return MockContext(
        financial={
            "A": {"TOTAL_SHARE": 5e10},
            "B": {"TOTAL_SHARE": 4e11 / 22.0},
        },
        price={
            "A": {
                "daily": {"close": 12.0},
                "weekly": {"open": 10.0, "close": 12.0},  # mid=11
            },
            "B": {
                "daily": {"close": 22.0},
                "weekly": {"open": 20.0, "close": 22.0},  # mid=21
            },
        },
        target_symbols=["A", "B"],
        new_symbols=["A", "B"],
        available_cash=cash,
        current_date="2024-01-01",  # 周一(2024-W01)
    )


def test_step_creates_buy_plans_for_new_symbols():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # 两只股票都应有 plan
    assert set(buyer._buy_plans.keys()) == {"A", "B"}
    # A 占 60%,B 占 40%
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    assert abs(plan_a["weekly_amount"] - 1_000_000 * 0.6 / 8) < 1.0
    assert abs(plan_b["weekly_amount"] - 1_000_000 * 0.4 / 8) < 1.0
    assert plan_a["market_cap"] == 6e11


def test_step_executes_first_week_buy():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # ctx.orders 应有两笔下单
    syms_ordered = {o[0] for o in ctx.orders}
    assert syms_ordered == {"A", "B"}
    # A: weekly_amount = 75000,price=11,shares = 75000/11=6818 → 取整 100 = 6800
    a_order = [o for o in ctx.orders if o[0] == "A"][0]
    assert a_order[1] == 6800


def test_step_does_not_buy_twice_in_same_week():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)
    initial_orders = len(ctx.orders)

    # 同一日期再次调用 step,不应产生新订单
    ctx.new_symbols = []  # 已分配过
    buyer.step(ctx)
    assert len(ctx.orders) == initial_orders


def test_step_buys_again_in_next_week():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # 推进一周
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"  # 下一周(2024-W02)
    buyer.step(ctx)

    # 应再次下单 A 与 B(共 4 笔)
    assert len(ctx.orders) == 4


def test_step_skips_symbol_removed_from_target():
    ctx = _ctx_with_two_new_symbols()
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # A 被 seller 移除
    ctx.target_symbols = ["B"]
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"
    a_orders_before = len([o for o in ctx.orders if o[0] == "A"])
    buyer.step(ctx)
    a_orders_after = len([o for o in ctx.orders if o[0] == "A"])
    assert a_orders_after == a_orders_before  # A 不再被买入


def test_step_finishes_after_buy_weeks():
    ctx = _ctx_with_two_new_symbols(cash=10_000_000)
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=2)
    # week 1
    buyer.step(ctx)
    # week 2
    ctx.new_symbols = []
    ctx.current_date = "2024-01-08"
    buyer.step(ctx)
    # week 3 — 应自动从 _buy_plans 中清除
    ctx.current_date = "2024-01-15"
    buyer.step(ctx)
    assert "A" not in buyer._buy_plans
    assert "B" not in buyer._buy_plans


def test_step_no_valuation_data_uses_equal_weight():
    ctx = MockContext(
        price={
            "A": {"weekly": {"open": 10.0, "close": 12.0}},
            "B": {"weekly": {"open": 20.0, "close": 22.0}},
        },
        target_symbols=["A", "B"],
        new_symbols=["A", "B"],
        available_cash=1_000_000,
        current_date="2024-01-01",
    )
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)

    # 无 mv 数据时等权(每只股票 mv=1.0)
    plan_a = buyer._buy_plans["A"]
    plan_b = buyer._buy_plans["B"]
    assert abs(plan_a["weekly_amount"] - plan_b["weekly_amount"]) < 1.0


def test_step_skips_when_no_price():
    # 提供 financial(派生 mv 用)但 price 为空,使本周买入跳过
    ctx = MockContext(
        financial={"A": {"TOTAL_SHARE": 5e10}},
        price={},  # 无价格 → 派生 mv 失败,等权 fallback,且 _execute_weekly_buys 也无 weekly 报价
        target_symbols=["A"],
        new_symbols=["A"],
        available_cash=1_000_000,
        current_date="2024-01-01",
    )
    buyer = MarketCapWeightedBatchBuyer(buy_weeks=8)
    buyer.step(ctx)
    # plan 已建,但本周不下单
    assert "A" in buyer._buy_plans
    assert ctx.orders == []
