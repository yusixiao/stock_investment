"""ConservativeRoughStrategy 集成测试(策略 screen pipeline 端到端)。

只验证管线串联正确性,各环节细节由 test_utils_conservative.py 覆盖。
"""

from __future__ import annotations

import pandas as pd

from tests.utils_test_helpers import MockContext

from services.backtest.strategies.experiments.conservative_rough.conservative_rough_strategy import ConservativeRoughStrategy


def _build_ctx_high_quality(sym="GOOD"):
    """构造一只全部环节都通过的样本股(粗算 R≈10pct + 商誉/净现金/FCF 都健康)。"""
    ctx = MockContext()
    # 5 年连续分红 + 3 年支付率 50%
    ctx.set_dividend_years({sym: 5})
    div_rows = [{"date": f"{2023 - i}-06-30", "cash_dividend": 0.5} for i in range(3)]
    ctx._dividend[sym] = pd.concat(
        [ctx._dividend[sym], pd.DataFrame(div_rows)], ignore_index=True
    )
    # 3 年 EPS=1.0 + 最新年报 NP / 总股本
    ctx.set_financial_history(
        {sym: [{"REPORT_DATE": f"{2023 - i}-12-31", "EPSJB": 1.0} for i in range(3)]}
    )
    ctx._financial[sym] = {
        "PARENTNETPROFIT": 1e9,
        "TOTAL_SHARE": 1e8,
        "ROEJQ": 15.0,
    }
    ctx._price[sym] = {"daily": {"close": 50.0}}  # 市值 50 亿,R≈10pct
    # Layer 2:全部健康
    ctx.set_balance(
        {
            sym: {
                "INDUSTRY_NAME": "电子",
                "GOODWILL": 1e8,
                "TOTAL_PARENT_EQUITY": 1e10,
                "MONETARYFUNDS": 5e9,
                "TOTAL_LIABILITIES": 1e9,
            }
        }
    )
    ctx.set_cashflow_history(
        {
            sym: [
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
    return ctx


def test_strategy_metadata():
    s = ConservativeRoughStrategy()
    assert s.frequency == "monthly"
    assert "min_dividend_years" in s.params
    assert "r_threshold_pct" in s.params


def test_screen_pipeline_passes_high_quality_stock():
    ctx = _build_ctx_high_quality("GOOD")
    s = ConservativeRoughStrategy()
    out = s.screen(ctx, ["GOOD"])
    assert out == ["GOOD"]


def test_screen_rejects_financial_industry():
    ctx = _build_ctx_high_quality("BANK")
    ctx._balance["BANK"]["INDUSTRY_NAME"] = "银行"
    s = ConservativeRoughStrategy()
    assert s.screen(ctx, ["BANK"]) == []


def test_screen_rejects_high_goodwill():
    ctx = _build_ctx_high_quality("GW")
    ctx._balance["GW"]["GOODWILL"] = 5e9  # 占权益 50% > 30%
    s = ConservativeRoughStrategy()
    assert s.screen(ctx, ["GW"]) == []


def test_screen_rejects_low_r():
    """市值放大 4 倍 → R ≈ 2.5pct < 5.2pct 门槛 → 被 conservative.r 否决。"""
    ctx = _build_ctx_high_quality("LOW_R")
    ctx._price["LOW_R"]["daily"]["close"] = 200.0
    s = ConservativeRoughStrategy()
    assert s.screen(ctx, ["LOW_R"]) == []


def test_screen_rejects_persistent_negative_fcf():
    ctx = _build_ctx_high_quality("FCF_BAD")
    ctx._cashflow_history["FCF_BAD"] = [
        {
            "REPORT_DATE": "2023-12-31",
            "NETCASH_OPERATE": 1e8,
            "CONSTRUCT_LONG_ASSET": 5e8,
        },
        {
            "REPORT_DATE": "2022-12-31",
            "NETCASH_OPERATE": 5e7,
            "CONSTRUCT_LONG_ASSET": 3e8,
        },
    ]
    s = ConservativeRoughStrategy()
    assert s.screen(ctx, ["FCF_BAD"]) == []


def test_screen_rejects_short_dividend_history():
    ctx = _build_ctx_high_quality("YOUNG")
    # 仅 2 年分红 < 默认 min_dividend_years=5
    rows = [
        {"date": "2023-06-30", "cash_dividend": 0.5},
        {"date": "2022-06-30", "cash_dividend": 0.5},
    ]
    ctx._dividend["YOUNG"] = pd.DataFrame(rows)
    s = ConservativeRoughStrategy()
    assert s.screen(ctx, ["YOUNG"]) == []
