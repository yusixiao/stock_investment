"""L2 第 5 项 — ROE 三年下降 > 30% disqualifier 单测。

口径:
  取近 3 年年报 ROEJQ(百分比,如 15.0 表示 15%)
  相对降幅 = (ROE_oldest − ROE_latest) / |ROE_oldest| > 0.30 → 否决
  数据缺失 / 不足 3 年 / 起始 ROE ≤ 0 → 保守放行
"""

from __future__ import annotations

from tests.utils_test_helpers import MockContext

from services.backtest.strategies.utils.conservative import reject_roe_decline_3y


def _set_roe_3y(ctx, sym, roe_list):
    """铺 3 年 ROEJQ(从最新到最旧顺序传入)。"""
    ctx.set_financial_history(
        {
            sym: [
                {"REPORT_DATE": f"{2023 - i}-12-31", "ROEJQ": roe_list[i]}
                for i in range(len(roe_list))
            ]
        }
    )


def test_roe_steady_passes():
    """ROE 稳定(15→14→15)→ 通过。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "S", [15.0, 14.0, 15.0])
    assert reject_roe_decline_3y(ctx, ["S"]) == ["S"]


def test_roe_growing_passes():
    """ROE 增长(20→15→10)→ latest=20, oldest=10,降幅 < 0 → 通过。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "G", [20.0, 15.0, 10.0])
    assert reject_roe_decline_3y(ctx, ["G"]) == ["G"]


def test_roe_decline_borderline_pass():
    """降幅 = 25%(20→15)< 30% → 通过。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "B", [15.0, 17.0, 20.0])  # latest=15, oldest=20, 降 25%
    assert reject_roe_decline_3y(ctx, ["B"]) == ["B"]


def test_roe_decline_rejected():
    """降幅 = 35%(20→13)> 30% → 否决。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "R", [13.0, 16.0, 20.0])  # latest=13, oldest=20, 降 35%
    assert reject_roe_decline_3y(ctx, ["R"]) == []


def test_roe_decline_severe_rejected():
    """ROE 大幅下降(20→5)→ 降 75% → 否决。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "X", [5.0, 10.0, 20.0])
    assert reject_roe_decline_3y(ctx, ["X"]) == []


def test_roe_missing_data_passes():
    """无 financial history → 保守放行。"""
    ctx = MockContext()
    assert reject_roe_decline_3y(ctx, ["MISSING"]) == ["MISSING"]


def test_roe_insufficient_years_passes():
    """只有 2 年数据 → 保守放行。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "S2", [15.0, 14.0])
    assert reject_roe_decline_3y(ctx, ["S2"]) == ["S2"]


def test_roe_oldest_zero_passes():
    """起始 ROE = 0(扭亏)→ 保守放行(避免除零)。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "Z", [10.0, 5.0, 0.0])
    assert reject_roe_decline_3y(ctx, ["Z"]) == ["Z"]


def test_roe_oldest_negative_passes():
    """起始 ROE < 0(亏损公司)→ 保守放行(扭亏不计入下降)。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "N", [10.0, 5.0, -5.0])
    assert reject_roe_decline_3y(ctx, ["N"]) == ["N"]


def test_roe_partial_missing_passes():
    """3 年数据但中间缺 ROEJQ → 有效样本 < 3 → 保守放行。"""
    ctx = MockContext()
    ctx.set_financial_history(
        {
            "P": [
                {"REPORT_DATE": "2023-12-31", "ROEJQ": 10.0},
                {"REPORT_DATE": "2022-12-31"},  # 缺 ROEJQ
                {"REPORT_DATE": "2021-12-31", "ROEJQ": 20.0},
            ]
        }
    )
    assert reject_roe_decline_3y(ctx, ["P"]) == ["P"]


def test_roe_custom_threshold():
    """自定义阈值 max_decline=0.20:从 20→17(降 15%)通过,从 20→15(降 25%)否决。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "A", [17.0, 18.0, 20.0])
    _set_roe_3y(ctx, "B", [15.0, 17.0, 20.0])
    # 注意 set_financial_history 会覆盖,要分开测
    ctx_a = MockContext()
    _set_roe_3y(ctx_a, "A", [17.0, 18.0, 20.0])
    assert reject_roe_decline_3y(ctx_a, ["A"], max_decline=0.20) == ["A"]
    ctx_b = MockContext()
    _set_roe_3y(ctx_b, "B", [15.0, 17.0, 20.0])
    assert reject_roe_decline_3y(ctx_b, ["B"], max_decline=0.20) == []


def test_roe_factor_recorded():
    """通过的股票应记录 roe_decline_pct factor。"""
    ctx = MockContext()
    _set_roe_3y(ctx, "F", [15.0, 17.0, 20.0])  # 降 25%
    reject_roe_decline_3y(ctx, ["F"])
    factors = ctx.get_factors("F")
    assert "roe_decline_pct" in factors
    assert abs(factors["roe_decline_pct"] - 0.25) < 1e-6


def test_roe_batch_mixed():
    """多股票混合:健康通过、衰退否决。"""
    ctx = MockContext()
    ctx.set_financial_history(
        {
            "OK": [
                {"REPORT_DATE": "2023-12-31", "ROEJQ": 15.0},
                {"REPORT_DATE": "2022-12-31", "ROEJQ": 14.0},
                {"REPORT_DATE": "2021-12-31", "ROEJQ": 16.0},
            ],
            "BAD": [
                {"REPORT_DATE": "2023-12-31", "ROEJQ": 5.0},
                {"REPORT_DATE": "2022-12-31", "ROEJQ": 12.0},
                {"REPORT_DATE": "2021-12-31", "ROEJQ": 20.0},
            ],
        }
    )
    result = reject_roe_decline_3y(ctx, ["OK", "BAD"])
    assert "OK" in result
    assert "BAD" not in result
