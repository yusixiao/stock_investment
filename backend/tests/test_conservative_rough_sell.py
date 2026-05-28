"""ConservativeRoughStrategy.on_sell — CPA 7 条基本面止损规则集成测试。

语义(2026-05-28 重写):
  critical 规则触发(净现金<0 / FCF yield<5% / FCF 连负 2 期)→ 清仓
  warning 规则触发(D/E 恶化 / 营收同比<-20% / 毛利率恶化 / 支付率降>30%)
    → 减仓到 50%,且每个 reason 只触发一次(_warning_seen 去重)

入场 baseline 在 on_buy 中 ctx.new_symbols 首次出现时记录。
"""

from __future__ import annotations

from strategies.examples.conservative_rough_strategy import ConservativeRoughStrategy

from .utils_test_helpers import MockContext


def _strat() -> ConservativeRoughStrategy:
    return ConservativeRoughStrategy()


# ---------- critical 类:清仓 ----------


def test_on_sell_critical_net_cash_negative_liquidates():
    """净现金 < 0 → 清仓。"""
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 1000})
    ctx.set_balance({"A": {"MONETARYFUNDS": 10.0, "TOTAL_LIABILITIES": 100.0}})

    s.on_sell(ctx)
    assert ctx.orders == [("A", -1000)]
    assert ctx.removed_targets == ["A"]
    assert "A" not in s._entry_baselines


def test_on_sell_critical_fcf_negative_2y_liquidates():
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 500})
    ctx.set_cashflow_history(
        {
            "A": [
                {"NETCASH_OPERATE": -100.0, "CONSTRUCT_LONG_ASSET": 0.0},
                {"NETCASH_OPERATE": -200.0, "CONSTRUCT_LONG_ASSET": 0.0},
            ]
        }
    )
    s.on_sell(ctx)
    assert ctx.orders == [("A", -500)]
    assert ctx.removed_targets == ["A"]


# ---------- warning 类:减仓到 50% ----------


def test_on_sell_warning_revenue_yoy_halves_position():
    """营收同比 < -20% → 减仓到 50%。"""
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 1000})
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 70.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    s.on_sell(ctx)
    # shares=1000,halved=500
    assert ctx.orders == [("A", -500)]
    assert ctx.removed_targets == []  # warning 不移出累计池
    assert "revenue_yoy_below_-20pct" in s._warning_seen["A"]


def test_on_sell_warning_same_reason_only_halves_once():
    """同一 warning reason 触发多次 → 只在首次减半,后续 noop。"""
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 1000})
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 50.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    s.on_sell(ctx)
    assert ctx.orders == [("A", -500)]

    # 第二次:同样 -50% yoy 仍然触发,但 _warning_seen 已记录 → noop
    ctx.orders.clear()
    ctx.set_positions({"A": 500})  # 模拟撮合后的剩余
    s.on_sell(ctx)
    assert ctx.orders == []


def test_on_sell_warning_new_reason_halves_again():
    """新 warning reason 出现 → 再次减半。"""
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 1000})

    # 先让 revenue_yoy 触发
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 70.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    s.on_sell(ctx)
    assert ctx.orders == [("A", -500)]

    # 第二次:新增 D/E 警告(无 baseline → absolute > 1.0)
    ctx.orders.clear()
    ctx.set_positions({"A": 500})
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 200.0, "TOTAL_PARENT_EQUITY": 100.0}})
    s.on_sell(ctx)
    # shares=500 → halved=250
    assert ctx.orders == [("A", -250)]
    assert "debt_equity_above_1.5x_baseline" in s._warning_seen["A"]
    assert "revenue_yoy_below_-20pct" in s._warning_seen["A"]


# ---------- critical 优先于 warning ----------


def test_on_sell_critical_overrides_warning_liquidates():
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 1000})
    # critical: 净现金 < 0
    ctx.set_balance({"A": {"MONETARYFUNDS": 10.0, "TOTAL_LIABILITIES": 100.0}})
    # warning: 营收 yoy
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 50.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    s.on_sell(ctx)
    # 清仓,而非减半
    assert ctx.orders == [("A", -1000)]
    assert ctx.removed_targets == ["A"]


# ---------- 无触发 noop ----------


def test_on_sell_healthy_position_noop():
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 1000})
    ctx.set_balance({"A": {"MONETARYFUNDS": 200.0, "TOTAL_LIABILITIES": 50.0}})
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 110.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    s.on_sell(ctx)
    assert ctx.orders == []
    assert ctx.removed_targets == []


def test_on_sell_zero_share_position_skipped():
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 0})
    ctx.set_balance({"A": {"MONETARYFUNDS": 10.0, "TOTAL_LIABILITIES": 100.0}})
    s.on_sell(ctx)
    assert ctx.orders == []


# ---------- baseline 由 on_buy 记录 ----------


def test_on_buy_records_baseline_for_new_symbols():
    """on_buy 首次见到 ctx.new_symbols 中的股票 → 记录 baseline。"""
    s = _strat()
    ctx = MockContext(
        new_symbols=["A"], target_symbols=["A"], current_date="2024-06-03"
    )
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 50.0, "TOTAL_PARENT_EQUITY": 100.0}})
    ctx.set_financial({"A": {"XSMLL": 30.0}})
    ctx.record_factor("A", "position_tier", "full")  # buyer 需要 tier
    s.on_buy(ctx)
    assert "A" in s._entry_baselines
    assert s._entry_baselines["A"]["debt_equity"] == 0.5
    assert s._entry_baselines["A"]["gross_margin"] == 30.0


def test_on_buy_does_not_overwrite_existing_baseline():
    """已记录 baseline 的股票第二次出现在 new_symbols 中 → 不覆盖。"""
    s = _strat()
    s._entry_baselines["A"] = {"debt_equity": 0.5, "gross_margin": 30.0, "payout": 0.5}
    ctx = MockContext(
        new_symbols=["A"], target_symbols=["A"], current_date="2024-06-03"
    )
    # 设了完全不同的 balance,但因为 baseline 已存在 → 不应被覆盖
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 999.0, "TOTAL_PARENT_EQUITY": 100.0}})
    s.on_buy(ctx)
    assert s._entry_baselines["A"]["debt_equity"] == 0.5  # 未被覆盖


# ---------- baseline 应用于规则 4/6/7 ----------


def test_on_sell_uses_recorded_baseline_for_rule6():
    """规则 6:current XSMLL = 20 < baseline 30 × 0.8 = 24 → warning 减半。"""
    s = _strat()
    s._entry_baselines["A"] = {
        "debt_equity": None,
        "gross_margin": 30.0,
        "payout": None,
    }
    ctx = MockContext()
    ctx.set_positions({"A": 1000})
    ctx.set_financial({"A": {"XSMLL": 20.0}})
    s.on_sell(ctx)
    assert ctx.orders == [("A", -500)]
    assert "gross_margin_below_0.8x_baseline" in s._warning_seen["A"]
