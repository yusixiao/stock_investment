"""测试 strategies/utils/conservative_sell.py — baseline 记录 + 7 条 CPA 止损规则。"""

import pytest

from strategies.utils import conservative_sell as cs

from .utils_test_helpers import MockContext


# ---------- record_entry_baseline ----------


def test_baseline_full_data():
    """三个字段都能从 mock 读出。"""
    ctx = MockContext()
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 50.0, "TOTAL_PARENT_EQUITY": 100.0}})
    ctx.set_financial({"A": {"XSMLL": 30.0, "EPSJB": 1.0}})
    ctx.set_financial_history(
        {
            "A": [
                {"REPORT_DATE": "2024-12-31", "EPSJB": 1.0},
                {"REPORT_DATE": "2023-12-31", "EPSJB": 1.0},
                {"REPORT_DATE": "2022-12-31", "EPSJB": 1.0},
            ]
        }
    )
    import pandas as pd

    ctx._dividend["A"] = pd.DataFrame(
        [
            {"date": "2024-06-30", "cash_dividend": 0.5},
            {"date": "2023-06-30", "cash_dividend": 0.5},
            {"date": "2022-06-30", "cash_dividend": 0.5},
        ]
    )
    base = cs.record_entry_baseline(ctx, "A")
    assert base["debt_equity"] == pytest.approx(0.5)
    assert base["gross_margin"] == pytest.approx(30.0)
    assert base["payout"] == pytest.approx(0.5)


def test_baseline_missing_fields_dont_block():
    """部分字段缺失时其他字段照常返回。"""
    ctx = MockContext()
    # 只设 D/E,gross_margin 与 payout 缺失
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 30.0, "TOTAL_PARENT_EQUITY": 60.0}})
    base = cs.record_entry_baseline(ctx, "A")
    assert base["debt_equity"] == pytest.approx(0.5)
    assert base["gross_margin"] is None
    assert base["payout"] is None


def test_baseline_no_data():
    ctx = MockContext()
    base = cs.record_entry_baseline(ctx, "A")
    assert base == {"debt_equity": None, "gross_margin": None, "payout": None}


# ---------- 规则 1: 净现金 < 0 (critical) ----------


def test_rule1_net_cash_negative_triggers_critical():
    ctx = MockContext()
    ctx.set_balance({"A": {"MONETARYFUNDS": 10.0, "TOTAL_LIABILITIES": 50.0}})
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert sev == "critical"
    assert "net_cash_negative" in reasons


def test_rule1_net_cash_positive_no_trigger():
    ctx = MockContext()
    ctx.set_balance({"A": {"MONETARYFUNDS": 100.0, "TOTAL_LIABILITIES": 30.0}})
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    # 仍可能触发其他规则,但 net_cash_negative 不在 reasons 里
    assert "net_cash_negative" not in reasons


# ---------- 规则 2: FCF yield < 5% (critical) ----------


def test_rule2_fcf_yield_below_5pct_triggers_critical():
    ctx = MockContext()
    ctx.set_cashflow(
        {"A": {"NETCASH_OPERATE": 1_000_000.0, "CONSTRUCT_LONG_ASSET": 0.0}}
    )
    # market_cap = 100 * 1_000_000 = 1e8;FCF/MC = 1e6/1e8 = 1% < 5%
    ctx.set_financial({"A": {"TOTAL_SHARE": 1_000_000.0}})
    ctx._price["A"] = {"daily": {"close": 100.0}}
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "fcf_yield_below_5pct" in reasons
    assert sev == "critical"


def test_rule2_fcf_yield_above_5pct_no_trigger():
    ctx = MockContext()
    ctx.set_cashflow(
        {"A": {"NETCASH_OPERATE": 10_000_000.0, "CONSTRUCT_LONG_ASSET": 0.0}}
    )
    ctx.set_financial({"A": {"TOTAL_SHARE": 1_000_000.0}})
    ctx._price["A"] = {"daily": {"close": 100.0}}
    # FCF/MC = 1e7/1e8 = 10% > 5%
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "fcf_yield_below_5pct" not in reasons


def test_rule2_missing_data_no_trigger():
    ctx = MockContext()
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "fcf_yield_below_5pct" not in reasons


# ---------- 规则 3: FCF 连续 2 期 < 0 (critical) ----------


def test_rule3_fcf_negative_2y_triggers_critical():
    ctx = MockContext()
    ctx.set_cashflow_history(
        {
            "A": [
                {"NETCASH_OPERATE": -100.0, "CONSTRUCT_LONG_ASSET": 0.0},
                {"NETCASH_OPERATE": -200.0, "CONSTRUCT_LONG_ASSET": 0.0},
            ]
        }
    )
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "fcf_negative_2y" in reasons
    assert sev == "critical"


# ---------- 规则 4: D/E > baseline×1.5 或 > 1.0 (warning) ----------


def test_rule4_de_above_baseline_15x_triggers_warning():
    ctx = MockContext()
    # current D/E = 200/100 = 2.0;baseline×1.5 = 0.5×1.5 = 0.75
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 200.0, "TOTAL_PARENT_EQUITY": 100.0}})
    sev, reasons = cs.cpa_fundamental_stop_loss(
        ctx, "A", {"debt_equity": 0.5, "gross_margin": None, "payout": None}
    )
    assert sev == "warning"
    assert "debt_equity_above_1.5x_baseline" in reasons


def test_rule4_de_below_baseline_no_trigger():
    ctx = MockContext()
    # current = 0.6;baseline×1.5 = 1.5;0.6 < 1.5 → no
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 60.0, "TOTAL_PARENT_EQUITY": 100.0}})
    sev, reasons = cs.cpa_fundamental_stop_loss(
        ctx, "A", {"debt_equity": 1.0, "gross_margin": None, "payout": None}
    )
    assert "debt_equity_above_1.5x_baseline" not in reasons


def test_rule4_no_baseline_uses_absolute_1pt0():
    ctx = MockContext()
    # current = 1.5 > 1.0 兜底
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 150.0, "TOTAL_PARENT_EQUITY": 100.0}})
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "debt_equity_above_1.5x_baseline" in reasons


def test_rule4_low_baseline_still_uses_1pt0_floor():
    """baseline×1.5 = 0.3 < 1.0,应使用 max(0.3, 1.0) = 1.0 作阈值。"""
    ctx = MockContext()
    # current = 0.9 < 1.0 → 不触发(虽然 > baseline×1.5=0.3)
    ctx.set_balance({"A": {"TOTAL_LIABILITIES": 90.0, "TOTAL_PARENT_EQUITY": 100.0}})
    sev, reasons = cs.cpa_fundamental_stop_loss(
        ctx, "A", {"debt_equity": 0.2, "gross_margin": None, "payout": None}
    )
    assert "debt_equity_above_1.5x_baseline" not in reasons


# ---------- 规则 5: 营收同比 < -20% (warning) ----------


def test_rule5_revenue_yoy_below_minus20_triggers_warning():
    ctx = MockContext()
    # 100 → 70 = -30%
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 70.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "revenue_yoy_below_-20pct" in reasons
    assert sev == "warning"


def test_rule5_revenue_flat_no_trigger():
    ctx = MockContext()
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 95.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "revenue_yoy_below_-20pct" not in reasons


def test_rule5_no_history_no_trigger():
    ctx = MockContext()
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "revenue_yoy_below_-20pct" not in reasons


# ---------- 规则 6: 毛利率 < baseline×0.8 (warning) ----------


def test_rule6_gross_margin_below_baseline_08_triggers_warning():
    ctx = MockContext()
    # current 20 < 30×0.8 = 24
    ctx.set_financial({"A": {"XSMLL": 20.0}})
    sev, reasons = cs.cpa_fundamental_stop_loss(
        ctx, "A", {"debt_equity": None, "gross_margin": 30.0, "payout": None}
    )
    assert sev == "warning"
    assert "gross_margin_below_0.8x_baseline" in reasons


def test_rule6_gross_margin_stable_no_trigger():
    ctx = MockContext()
    ctx.set_financial({"A": {"XSMLL": 28.0}})  # 28 > 30×0.8=24
    sev, reasons = cs.cpa_fundamental_stop_loss(
        ctx, "A", {"debt_equity": None, "gross_margin": 30.0, "payout": None}
    )
    assert "gross_margin_below_0.8x_baseline" not in reasons


def test_rule6_no_baseline_skipped():
    ctx = MockContext()
    ctx.set_financial({"A": {"XSMLL": 5.0}})
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "gross_margin_below_0.8x_baseline" not in reasons


# ---------- 规则 7: 支付率降幅 > 30% (warning) ----------


def test_rule7_payout_decline_above_30pct_triggers_warning():
    ctx = MockContext()
    # 模拟当前 payout = 0.3,baseline = 0.6 → 相对降幅 50%
    ctx.set_financial_history(
        {
            "A": [
                {"REPORT_DATE": "2024-12-31", "EPSJB": 1.0},
                {"REPORT_DATE": "2023-12-31", "EPSJB": 1.0},
                {"REPORT_DATE": "2022-12-31", "EPSJB": 1.0},
            ]
        }
    )
    import pandas as pd

    ctx._dividend["A"] = pd.DataFrame(
        [
            {"date": "2024-06-30", "cash_dividend": 0.3},
            {"date": "2023-06-30", "cash_dividend": 0.3},
            {"date": "2022-06-30", "cash_dividend": 0.3},
        ]
    )
    sev, reasons = cs.cpa_fundamental_stop_loss(
        ctx, "A", {"debt_equity": None, "gross_margin": None, "payout": 0.6}
    )
    assert sev == "warning"
    assert "payout_decline_above_30pct" in reasons


def test_rule7_payout_stable_no_trigger():
    ctx = MockContext()
    ctx.set_financial_history(
        {
            "A": [
                {"REPORT_DATE": "2024-12-31", "EPSJB": 1.0},
                {"REPORT_DATE": "2023-12-31", "EPSJB": 1.0},
                {"REPORT_DATE": "2022-12-31", "EPSJB": 1.0},
            ]
        }
    )
    import pandas as pd

    ctx._dividend["A"] = pd.DataFrame(
        [
            {"date": "2024-06-30", "cash_dividend": 0.5},
            {"date": "2023-06-30", "cash_dividend": 0.5},
            {"date": "2022-06-30", "cash_dividend": 0.5},
        ]
    )
    sev, reasons = cs.cpa_fundamental_stop_loss(
        ctx, "A", {"debt_equity": None, "gross_margin": None, "payout": 0.5}
    )
    assert "payout_decline_above_30pct" not in reasons


def test_rule7_no_baseline_skipped():
    ctx = MockContext()
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert "payout_decline_above_30pct" not in reasons


# ---------- 严重度优先级 ----------


def test_critical_overrides_warning():
    """critical 与 warning 同时触发时,severity = critical。"""
    ctx = MockContext()
    # 净现金 < 0 (critical)
    ctx.set_balance({"A": {"MONETARYFUNDS": 10.0, "TOTAL_LIABILITIES": 200.0}})
    # 同时 D/E warning(current = 200/X 但 equity 缺失,改用 income 触发 yoy warning)
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 50.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert sev == "critical"
    assert "net_cash_negative" in reasons
    assert "revenue_yoy_below_-20pct" in reasons


def test_no_triggers_returns_none():
    ctx = MockContext()
    # 所有数据都健康
    ctx.set_balance({"A": {"MONETARYFUNDS": 200.0, "TOTAL_LIABILITIES": 50.0}})
    ctx.set_income_history(
        {
            "A": [
                {"TOTAL_OPERATE_INCOME": 110.0},
                {"TOTAL_OPERATE_INCOME": 100.0},
            ]
        }
    )
    sev, reasons = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    assert sev is None
    assert reasons == []


def test_baseline_none_equivalent_to_empty_dict():
    ctx = MockContext()
    sev1, r1 = cs.cpa_fundamental_stop_loss(ctx, "A", None)
    sev2, r2 = cs.cpa_fundamental_stop_loss(ctx, "A", {})
    assert sev1 == sev2 and r1 == r2
