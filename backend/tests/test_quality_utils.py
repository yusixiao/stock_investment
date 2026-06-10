"""quality utils 单测 — 行业判断 / 资产负债率 / CFO/NP / ROE 趋势 / 综合门槛。"""

from __future__ import annotations

from tests.utils_test_helpers import MockContext

from strategies.utils import quality


# ===== 行业判断 =====
def test_get_industry_from_balance():
    ctx = MockContext()
    ctx.set_balance({"600519.SH": {"INDUSTRY_NAME": "白酒"}})
    assert quality.get_industry(ctx, "600519.SH") == "白酒"


def test_get_industry_missing_returns_none():
    ctx = MockContext()
    assert quality.get_industry(ctx, "X") is None


def test_get_industry_empty_string_returns_none():
    ctx = MockContext()
    ctx.set_balance({"X": {"INDUSTRY_NAME": "  "}})
    assert quality.get_industry(ctx, "X") is None


def test_is_financial_industry_keywords():
    assert quality.is_financial_industry("股份制银行")
    assert quality.is_financial_industry("人寿保险")
    assert quality.is_financial_industry("证券")
    assert quality.is_financial_industry("信托")
    assert quality.is_financial_industry("金融控股")
    assert not quality.is_financial_industry("白酒")
    assert not quality.is_financial_industry(None)
    assert not quality.is_financial_industry("")


# ===== 资产负债率 =====
def test_get_debt_ratio_normal():
    ctx = MockContext()
    ctx.set_balance({"X": {"TOTAL_LIABILITIES": 60.0, "TOTAL_ASSETS": 100.0}})
    assert quality.get_debt_ratio(ctx, "X") == 0.60


def test_get_debt_ratio_missing_field():
    ctx = MockContext()
    ctx.set_balance({"X": {"TOTAL_ASSETS": 100.0}})
    assert quality.get_debt_ratio(ctx, "X") is None


def test_get_debt_ratio_zero_assets():
    ctx = MockContext()
    ctx.set_balance({"X": {"TOTAL_LIABILITIES": 10.0, "TOTAL_ASSETS": 0.0}})
    assert quality.get_debt_ratio(ctx, "X") is None


# ===== CFO/NP =====
def test_get_cfo_to_np_healthy():
    ctx = MockContext()
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": 80.0}]})
    ctx.set_income_history({"X": [{"PARENT_NETPROFIT": 100.0}]})
    assert quality.get_cfo_to_np_ratio(ctx, "X") == 0.80


def test_get_cfo_to_np_negative_np():
    ctx = MockContext()
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": 50.0}]})
    ctx.set_income_history({"X": [{"PARENT_NETPROFIT": -10.0}]})
    # 净利润 ≤ 0 时返 None
    assert quality.get_cfo_to_np_ratio(ctx, "X") is None


def test_get_cfo_to_np_missing_history():
    ctx = MockContext()
    assert quality.get_cfo_to_np_ratio(ctx, "X") is None


def test_get_cfo_positive():
    ctx = MockContext()
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": 1234.5}]})
    assert quality.get_cfo(ctx, "X") == 1234.5


def test_get_cfo_missing():
    ctx = MockContext()
    assert quality.get_cfo(ctx, "X") is None


# ===== ROE 连续大跌 =====
def test_roe_decline_two_consecutive_drops():
    ctx = MockContext()
    # 倒序:最新 → 最旧。10 → 15 → 30:相邻两次都下降 ≥ 30%
    ctx.set_financial_history(
        {
            "X": [
                {"ROEJQ": 10.0},
                {"ROEJQ": 15.0},
                {"ROEJQ": 30.0},
            ]
        }
    )
    assert quality.has_severe_roe_decline(ctx, "X") is True


def test_roe_decline_only_one_drop_is_healthy():
    ctx = MockContext()
    # 15 → 16 → 30:仅一次大跌(16→30:46% 但只有 1 次,还需另一次)
    # 实际:相邻 i=0 (15→16):drop=(16-15)/16=6%, 不算
    #       相邻 i=1 (16→30):drop=(30-16)/30=46%, 算
    # 只有 1 次 → False
    ctx.set_financial_history(
        {
            "X": [
                {"ROEJQ": 15.0},
                {"ROEJQ": 16.0},
                {"ROEJQ": 30.0},
            ]
        }
    )
    assert quality.has_severe_roe_decline(ctx, "X") is False


def test_roe_decline_insufficient_history():
    ctx = MockContext()
    ctx.set_financial_history({"X": [{"ROEJQ": 10.0}, {"ROEJQ": 20.0}]})
    assert quality.has_severe_roe_decline(ctx, "X") is None


def test_roe_decline_missing_value():
    ctx = MockContext()
    ctx.set_financial_history(
        {
            "X": [
                {"ROEJQ": 10.0},
                {"ROEJQ": None},
                {"ROEJQ": 30.0},
            ]
        }
    )
    assert quality.has_severe_roe_decline(ctx, "X") is None


def test_roe_decline_negative_baseline_skipped():
    """起点为 0 或负时不能算百分比下降,不应误判为下降。"""
    ctx = MockContext()
    ctx.set_financial_history(
        {
            "X": [
                {"ROEJQ": 5.0},
                {"ROEJQ": 0.0},
                {"ROEJQ": -3.0},
            ]
        }
    )
    assert quality.has_severe_roe_decline(ctx, "X") is False


# ===== 综合门槛 =====
def test_passes_quality_filter_healthy():
    ctx = MockContext()
    ctx.set_balance(
        {
            "X": {
                "INDUSTRY_NAME": "白酒",
                "TOTAL_LIABILITIES": 30.0,
                "TOTAL_ASSETS": 100.0,
            }
        }
    )
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": 80.0}]})
    ctx.set_income_history({"X": [{"PARENT_NETPROFIT": 100.0}]})
    ctx.set_financial_history(
        {"X": [{"ROEJQ": 25.0}, {"ROEJQ": 24.0}, {"ROEJQ": 23.0}]}
    )
    ok, reason = quality.passes_quality_filter(ctx, "X")
    assert ok is True
    assert reason == "ok"


def test_passes_quality_filter_rejects_negative_cfo():
    ctx = MockContext()
    ctx.set_balance({"X": {"INDUSTRY_NAME": "白酒"}})
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": -10.0}]})
    ok, reason = quality.passes_quality_filter(ctx, "X")
    assert ok is False
    assert reason == "negative_cfo"


def test_passes_quality_filter_rejects_low_cfo_np():
    ctx = MockContext()
    ctx.set_balance({"X": {"INDUSTRY_NAME": "白酒"}})
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": 30.0}]})
    ctx.set_income_history({"X": [{"PARENT_NETPROFIT": 100.0}]})
    ok, reason = quality.passes_quality_filter(ctx, "X")
    assert ok is False
    assert "low_cfo_np_ratio" in reason


def test_passes_quality_filter_rejects_high_debt():
    ctx = MockContext()
    ctx.set_balance(
        {
            "X": {
                "INDUSTRY_NAME": "钢铁",
                "TOTAL_LIABILITIES": 80.0,
                "TOTAL_ASSETS": 100.0,
            }
        }
    )
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": 80.0}]})
    ctx.set_income_history({"X": [{"PARENT_NETPROFIT": 100.0}]})
    ok, reason = quality.passes_quality_filter(ctx, "X")
    assert ok is False
    assert "high_debt_ratio" in reason


def test_passes_quality_filter_financial_exempt_from_debt_and_cfo():
    """金融业即使 CFO < 0、负债率 95%,也应通过(豁免)。"""
    ctx = MockContext()
    ctx.set_balance(
        {
            "X": {
                "INDUSTRY_NAME": "股份制银行",
                "TOTAL_LIABILITIES": 95.0,
                "TOTAL_ASSETS": 100.0,
            }
        }
    )
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": -50.0}]})
    ctx.set_income_history({"X": [{"PARENT_NETPROFIT": 100.0}]})
    ctx.set_financial_history(
        {"X": [{"ROEJQ": 12.0}, {"ROEJQ": 12.0}, {"ROEJQ": 12.0}]}
    )
    ok, reason = quality.passes_quality_filter(ctx, "X")
    assert ok is True
    assert reason == "ok"


def test_passes_quality_filter_rejects_roe_decline():
    ctx = MockContext()
    ctx.set_balance({"X": {"INDUSTRY_NAME": "白酒"}})
    ctx.set_cashflow_history({"X": [{"NETCASH_OPERATE": 80.0}]})
    ctx.set_income_history({"X": [{"PARENT_NETPROFIT": 100.0}]})
    ctx.set_financial_history(
        {
            "X": [
                {"ROEJQ": 5.0},
                {"ROEJQ": 10.0},
                {"ROEJQ": 25.0},
            ]
        }
    )
    ok, reason = quality.passes_quality_filter(ctx, "X")
    assert ok is False
    assert reason == "roe_severe_decline"


def test_passes_quality_filter_missing_data_passes():
    """缺失数据 → 默认放行(返 True),决策权交上层。"""
    ctx = MockContext()
    ok, reason = quality.passes_quality_filter(ctx, "X")
    assert ok is True
    assert reason == "ok"
