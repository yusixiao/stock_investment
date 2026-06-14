"""L1.3 信誉评级单测(strategies/utils/conservative.py — credibility 部分)。

三维度聚合 → high / mid / low:
- 维度1: 5 年营收 CV(变异系数)
- 维度2: 利润调整幅度(非经常损益占比)
- 维度3: λ warning(高杠杆/商誉/净现金/FCF 四项)
"""

from __future__ import annotations

from tests.utils_test_helpers import MockContext

from services.backtest.strategies.utils.conservative import (
    _compute_profit_adjustment_5y,
    _compute_revenue_cv_5y,
    _count_lambda_warnings,
    compute_credibility_rating,
    record_credibility_factors,
)


# ---------- _compute_revenue_cv_5y ----------


def _set_income_5y(ctx, sym, revenues):
    """铺设 5 年 income 年报 TOTAL_OPERATE_INCOME(从最新到最旧)。"""
    ctx.set_income_history(
        {
            sym: [
                {
                    "REPORT_DATE": f"{2023 - i}-12-31",
                    "TOTAL_OPERATE_INCOME": revenues[i],
                }
                for i in range(len(revenues))
            ]
        }
    )


def test_revenue_cv_stable():
    """营收稳定(100,101,99,100,100)→ CV ≈ 0.01 → 应评为 A。"""
    ctx = MockContext()
    _set_income_5y(ctx, "S", [100, 101, 99, 100, 100])
    cv = _compute_revenue_cv_5y(ctx, "S")
    assert cv is not None
    assert cv < 0.15


def test_revenue_cv_volatile():
    """营收波动(100,200,50,300,10)→ CV > 0.30 → 应评为 C。"""
    ctx = MockContext()
    _set_income_5y(ctx, "V", [100, 200, 50, 300, 10])
    cv = _compute_revenue_cv_5y(ctx, "V")
    assert cv is not None
    assert cv > 0.30


def test_revenue_cv_moderate():
    """营收中等波动(100,130,70,120,80)→ CV ≈ 0.25 ∈ [0.15,0.30] → B。"""
    ctx = MockContext()
    _set_income_5y(ctx, "M", [100, 130, 70, 120, 80])
    cv = _compute_revenue_cv_5y(ctx, "M")
    assert cv is not None
    assert 0.15 <= cv <= 0.30


def test_revenue_cv_insufficient_data():
    """不足 3 年 → None。"""
    ctx = MockContext()
    _set_income_5y(ctx, "X", [100, 200])
    assert _compute_revenue_cv_5y(ctx, "X") is None


def test_revenue_cv_missing():
    """无数据 → None。"""
    ctx = MockContext()
    assert _compute_revenue_cv_5y(ctx, "MISSING") is None


def test_revenue_cv_zero_mean():
    """均值为 0 → None(避免除零)。"""
    ctx = MockContext()
    _set_income_5y(ctx, "Z", [0, 0, 0, 0, 0])
    assert _compute_revenue_cv_5y(ctx, "Z") is None


# ---------- _compute_profit_adjustment_5y ----------


def _set_income_profit_5y(ctx, sym, parent_list, deduct_list):
    """铺设 5 年 income 年报 PARENT_NETPROFIT + DEDUCT_PARENT_NETPROFIT。"""
    ctx.set_income_history(
        {
            sym: [
                {
                    "REPORT_DATE": f"{2023 - i}-12-31",
                    "PARENT_NETPROFIT": parent_list[i],
                    "DEDUCT_PARENT_NETPROFIT": deduct_list[i],
                }
                for i in range(len(parent_list))
            ]
        }
    )


def test_profit_adjustment_low():
    """归母与扣非接近 → 幅度 < 0.10 → A。"""
    ctx = MockContext()
    _set_income_profit_5y(ctx, "S", [100, 100, 100, 100, 100], [95, 96, 97, 94, 95])
    adj = _compute_profit_adjustment_5y(ctx, "S")
    assert adj is not None
    assert adj < 0.10


def test_profit_adjustment_high():
    """非经常损益占比大 → 幅度 > 0.25 → C。"""
    ctx = MockContext()
    _set_income_profit_5y(ctx, "H", [100, 100, 100, 100, 100], [50, 60, 70, 55, 65])
    adj = _compute_profit_adjustment_5y(ctx, "H")
    assert adj is not None
    assert adj > 0.25


def test_profit_adjustment_moderate():
    """中等非经常占比 → 幅度 0.10~0.25 → B。"""
    ctx = MockContext()
    _set_income_profit_5y(ctx, "M", [100, 100, 100, 100, 100], [85, 88, 90, 82, 87])
    adj = _compute_profit_adjustment_5y(ctx, "M")
    assert adj is not None
    assert 0.10 <= adj <= 0.25


def test_profit_adjustment_insufficient():
    """不足 2 年有效 → None。"""
    ctx = MockContext()
    ctx.set_income_history(
        {
            "X": [
                {
                    "REPORT_DATE": "2023-12-31",
                    "PARENT_NETPROFIT": 100,
                    "DEDUCT_PARENT_NETPROFIT": 90,
                },
            ]
        }
    )
    assert _compute_profit_adjustment_5y(ctx, "X") is None


def test_profit_adjustment_zero_parent():
    """归母净利润为 0 → 该年跳过(不除零)。"""
    ctx = MockContext()
    _set_income_profit_5y(ctx, "Z", [0, 100, 100], [0, 90, 90])
    adj = _compute_profit_adjustment_5y(ctx, "Z")
    assert adj is not None
    assert abs(adj - 0.10) < 1e-6


# ---------- _count_lambda_warnings ----------


def test_lambda_warnings_zero():
    """全部健康 → 0。"""
    ctx = MockContext()
    ctx.set_balance(
        {
            "OK": {
                "DEBT_ASSET_RATIO": 40,
                "GOODWILL": 1e7,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 5e9,
                "TOTAL_LIABILITIES": 1e9,
            }
        }
    )
    ctx.set_cashflow_history(
        {
            "OK": [
                {
                    "REPORT_DATE": "2023-12-31",
                    "NETCASH_OPERATE": 5e8,
                    "CONSTRUCT_LONG_ASSET": 1e8,
                },
                {
                    "REPORT_DATE": "2022-12-31",
                    "NETCASH_OPERATE": 4e8,
                    "CONSTRUCT_LONG_ASSET": 1e8,
                },
            ]
        }
    )
    assert _count_lambda_warnings(ctx, "OK") == 0


def test_lambda_warnings_high_leverage():
    """资产负债率 > 80 → 1。"""
    ctx = MockContext()
    ctx.set_balance(
        {
            "HL": {
                "DEBT_ASSET_RATIO": 85,
                "GOODWILL": 0,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 5e9,
                "TOTAL_LIABILITIES": 1e9,
            }
        }
    )
    assert _count_lambda_warnings(ctx, "HL") == 1


def test_lambda_warnings_goodwill():
    """商誉 > 30% → 1。"""
    ctx = MockContext()
    ctx.set_balance(
        {
            "GW": {
                "DEBT_ASSET_RATIO": 40,
                "GOODWILL": 5e8,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 5e9,
                "TOTAL_LIABILITIES": 1e9,
            }
        }
    )
    assert _count_lambda_warnings(ctx, "GW") == 1


def test_lambda_warnings_net_cash():
    """净现金 < 0 → 1。"""
    ctx = MockContext()
    ctx.set_balance(
        {
            "NC": {
                "DEBT_ASSET_RATIO": 40,
                "GOODWILL": 0,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 1e9,
                "TOTAL_LIABILITIES": 5e9,
            }
        }
    )
    assert _count_lambda_warnings(ctx, "NC") == 1


def test_lambda_warnings_fcf():
    """FCF 2 年持续为负 → 1。"""
    ctx = MockContext()
    ctx.set_balance(
        {
            "FCF": {
                "DEBT_ASSET_RATIO": 40,
                "GOODWILL": 0,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 5e9,
                "TOTAL_LIABILITIES": 1e9,
            }
        }
    )
    ctx.set_cashflow_history(
        {
            "FCF": [
                {
                    "REPORT_DATE": "2023-12-31",
                    "NETCASH_OPERATE": 1e8,
                    "CONSTRUCT_LONG_ASSET": 2e8,
                },
                {
                    "REPORT_DATE": "2022-12-31",
                    "NETCASH_OPERATE": 5e7,
                    "CONSTRUCT_LONG_ASSET": 1e8,
                },
            ]
        }
    )
    assert _count_lambda_warnings(ctx, "FCF") == 1


def test_lambda_warnings_multiple():
    """高杠杆 + 商誉 + 净现金负 + FCF 负 → 4。"""
    ctx = MockContext()
    ctx.set_balance(
        {
            "BAD": {
                "DEBT_ASSET_RATIO": 85,
                "GOODWILL": 5e8,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 1e9,
                "TOTAL_LIABILITIES": 5e9,
            }
        }
    )
    ctx.set_cashflow_history(
        {
            "BAD": [
                {
                    "REPORT_DATE": "2023-12-31",
                    "NETCASH_OPERATE": 1e8,
                    "CONSTRUCT_LONG_ASSET": 2e8,
                },
                {
                    "REPORT_DATE": "2022-12-31",
                    "NETCASH_OPERATE": 5e7,
                    "CONSTRUCT_LONG_ASSET": 1e8,
                },
            ]
        }
    )
    assert _count_lambda_warnings(ctx, "BAD") == 4


def test_lambda_warnings_no_data():
    """数据缺失 → 0(保守不计数)。"""
    ctx = MockContext()
    assert _count_lambda_warnings(ctx, "MISSING") == 0


# ---------- compute_credibility_rating ----------


def _setup_high_rating(ctx, sym):
    """铺设三维度均为 A 的数据。"""
    _set_income_5y(ctx, sym, [100, 101, 99, 100, 100])
    _set_income_profit_5y(ctx, sym, [100, 100, 100, 100, 100], [95, 96, 97, 94, 95])
    # 合并到同一 history
    ctx.set_income_history(
        {
            sym: [
                {
                    "REPORT_DATE": f"{2023 - i}-12-31",
                    "TOTAL_OPERATE_INCOME": [100, 101, 99, 100, 100][i],
                    "PARENT_NETPROFIT": [100, 100, 100, 100, 100][i],
                    "DEDUCT_PARENT_NETPROFIT": [95, 96, 97, 94, 95][i],
                }
                for i in range(5)
            ]
        }
    )
    ctx.set_balance(
        {
            sym: {
                "DEBT_ASSET_RATIO": 40,
                "GOODWILL": 1e7,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 5e9,
                "TOTAL_LIABILITIES": 1e9,
            }
        }
    )


def _setup_low_rating(ctx, sym):
    """铺设三维度均为 C 的数据。"""
    ctx.set_income_history(
        {
            sym: [
                {
                    "REPORT_DATE": f"{2023 - i}-12-31",
                    "TOTAL_OPERATE_INCOME": [100, 300, 10, 500, 5][i],
                    "PARENT_NETPROFIT": [100, 100, 100, 100, 100][i],
                    "DEDUCT_PARENT_NETPROFIT": [40, 50, 60, 45, 55][i],
                }
                for i in range(5)
            ]
        }
    )
    ctx.set_balance(
        {
            sym: {
                "DEBT_ASSET_RATIO": 85,
                "GOODWILL": 5e8,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 1e9,
                "TOTAL_LIABILITIES": 5e9,
            }
        }
    )
    ctx.set_cashflow_history(
        {
            sym: [
                {
                    "REPORT_DATE": "2023-12-31",
                    "NETCASH_OPERATE": 1e8,
                    "CONSTRUCT_LONG_ASSET": 2e8,
                },
                {
                    "REPORT_DATE": "2022-12-31",
                    "NETCASH_OPERATE": 5e7,
                    "CONSTRUCT_LONG_ASSET": 1e8,
                },
            ]
        }
    )


def test_credibility_rating_high():
    """三维度全 A → high。"""
    ctx = MockContext()
    _setup_high_rating(ctx, "GOOD")
    assert compute_credibility_rating(ctx, "GOOD") == "high"
    factors = ctx.get_factors("GOOD")
    assert factors["credibility_rating"] == "high"
    assert factors["revenue_cv"] is not None
    assert factors["revenue_cv"] < 0.15
    assert factors["profit_adjustment"] is not None
    assert factors["profit_adjustment"] < 0.10
    assert factors["lambda_warnings"] == 0


def test_credibility_rating_low():
    """含 C → low。"""
    ctx = MockContext()
    _setup_low_rating(ctx, "BAD")
    assert compute_credibility_rating(ctx, "BAD") == "low"


def test_credibility_rating_mid():
    """混合 A/B → mid。"""
    ctx = MockContext()
    # CV: ≈0.25(B), profit adj: <0.10(A), warnings: 0(A) → A,A,B → mid
    ctx.set_income_history(
        {
            "MID": [
                {
                    "REPORT_DATE": f"{2023 - i}-12-31",
                    "TOTAL_OPERATE_INCOME": [100, 130, 70, 120, 80][i],
                    "PARENT_NETPROFIT": [100, 100, 100, 100, 100][i],
                    "DEDUCT_PARENT_NETPROFIT": [95, 96, 97, 94, 95][i],
                }
                for i in range(5)
            ]
        }
    )
    ctx.set_balance(
        {
            "MID": {
                "DEBT_ASSET_RATIO": 40,
                "GOODWILL": 1e7,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 5e9,
                "TOTAL_LIABILITIES": 1e9,
            }
        }
    )
    assert compute_credibility_rating(ctx, "MID") == "mid"


def test_credibility_rating_missing_income_mid():
    """income 缺失 → CV 和 profit adj 都为 B,warnings: 0(A) → A,B,B → mid。"""
    ctx = MockContext()
    ctx.set_balance(
        {
            "NOINC": {
                "DEBT_ASSET_RATIO": 40,
                "GOODWILL": 1e7,
                "TOTAL_PARENT_EQUITY": 1e9,
                "MONETARYFUNDS": 5e9,
                "TOTAL_LIABILITIES": 1e9,
            }
        }
    )
    assert compute_credibility_rating(ctx, "NOINC") == "mid"


# ---------- record_credibility_factors ----------


def test_record_credibility_factors():
    """批量记录,不筛除。"""
    ctx = MockContext()
    _setup_high_rating(ctx, "A")
    _setup_low_rating(ctx, "B")
    record_credibility_factors(ctx, ["A", "B"])
    assert ctx.get_factors("A")["credibility_rating"] == "high"
    assert ctx.get_factors("B")["credibility_rating"] == "low"
    assert "A" in ctx.passed_symbols("conservative.credibility")
    assert "B" in ctx.passed_symbols("conservative.credibility")
