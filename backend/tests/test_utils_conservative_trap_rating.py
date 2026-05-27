"""L2.5 trap_rating 软评分单测(strategies/utils/conservative.py)。

把 L2.2-L2.5 四项 disqualifier(商誉/净现金/FCF/ROE 下降)从硬否决改为软评分:
  触发 0 → low(健康)
  触发 1 → mid(警惕)
  触发 ≥2 → high(高风险)

金融股(L2.1)仍走硬否决,不参与此聚合(cpa 框架方法论盲点)。
数据缺失维度计为"未触发"(与现有 reject_* 保守放行语义一致)。
"""

from __future__ import annotations

from tests.utils_test_helpers import MockContext

from strategies.utils.conservative import (
    compute_trap_rating,
    record_trap_rating,
)


def _set_balance(ctx, sym, **kwargs):
    defaults = {
        "GOODWILL": 0,
        "TOTAL_PARENT_EQUITY": 1e9,
        "MONETARYFUNDS": 5e9,
        "TOTAL_LIABILITIES": 1e9,
    }
    defaults.update(kwargs)
    ctx.set_balance({sym: defaults})


def _set_healthy_cashflow(ctx, sym):
    """两年都正 FCF。"""
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


def _set_bad_cashflow(ctx, sym):
    """两年都负 FCF。"""
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


def _set_roe_history(ctx, sym, roe_list):
    ctx.set_financial_history(
        {
            sym: [
                {"REPORT_DATE": f"{2023 - i}-12-31", "ROEJQ": roe_list[i]}
                for i in range(len(roe_list))
            ]
        }
    )


# ---------- compute_trap_rating ----------


def test_trap_rating_all_healthy_low():
    """4 项全健康 → low,triggered=[]。"""
    ctx = MockContext()
    _set_balance(ctx, "OK")
    _set_healthy_cashflow(ctx, "OK")
    _set_roe_history(ctx, "OK", [15.0, 14.0, 16.0])
    rating, triggered = compute_trap_rating(ctx, "OK")
    assert rating == "low"
    assert triggered == []


def test_trap_rating_one_trigger_mid():
    """只商誉超标 → mid,triggered=['goodwill']。"""
    ctx = MockContext()
    _set_balance(ctx, "GW", GOODWILL=5e8, TOTAL_PARENT_EQUITY=1e9)
    _set_healthy_cashflow(ctx, "GW")
    _set_roe_history(ctx, "GW", [15.0, 14.0, 16.0])
    rating, triggered = compute_trap_rating(ctx, "GW")
    assert rating == "mid"
    assert triggered == ["goodwill"]


def test_trap_rating_two_triggers_high():
    """商誉 + 净现金负 → high。"""
    ctx = MockContext()
    _set_balance(ctx, "BAD2", GOODWILL=5e8, MONETARYFUNDS=1e9, TOTAL_LIABILITIES=5e9)
    _set_healthy_cashflow(ctx, "BAD2")
    _set_roe_history(ctx, "BAD2", [15.0, 14.0, 16.0])
    rating, triggered = compute_trap_rating(ctx, "BAD2")
    assert rating == "high"
    assert set(triggered) == {"goodwill", "net_cash"}


def test_trap_rating_three_triggers_high():
    """商誉 + 净现金负 + FCF 负 → high。"""
    ctx = MockContext()
    _set_balance(ctx, "BAD3", GOODWILL=5e8, MONETARYFUNDS=1e9, TOTAL_LIABILITIES=5e9)
    _set_bad_cashflow(ctx, "BAD3")
    _set_roe_history(ctx, "BAD3", [15.0, 14.0, 16.0])
    rating, triggered = compute_trap_rating(ctx, "BAD3")
    assert rating == "high"
    assert set(triggered) == {"goodwill", "net_cash", "fcf"}


def test_trap_rating_all_four_triggered():
    """4 项全触发 → high。"""
    ctx = MockContext()
    _set_balance(ctx, "BAD4", GOODWILL=5e8, MONETARYFUNDS=1e9, TOTAL_LIABILITIES=5e9)
    _set_bad_cashflow(ctx, "BAD4")
    _set_roe_history(ctx, "BAD4", [5.0, 12.0, 20.0])  # 降 75%
    rating, triggered = compute_trap_rating(ctx, "BAD4")
    assert rating == "high"
    assert set(triggered) == {"goodwill", "net_cash", "fcf", "roe_decline"}


def test_trap_rating_only_roe_decline_mid():
    """只 ROE 下降 → mid。"""
    ctx = MockContext()
    _set_balance(ctx, "RD")
    _set_healthy_cashflow(ctx, "RD")
    _set_roe_history(ctx, "RD", [5.0, 12.0, 20.0])  # 降 75%
    rating, triggered = compute_trap_rating(ctx, "RD")
    assert rating == "mid"
    assert triggered == ["roe_decline"]


def test_trap_rating_only_fcf_mid():
    """只 FCF 持续负 → mid。"""
    ctx = MockContext()
    _set_balance(ctx, "FCF")
    _set_bad_cashflow(ctx, "FCF")
    _set_roe_history(ctx, "FCF", [15.0, 14.0, 16.0])
    rating, triggered = compute_trap_rating(ctx, "FCF")
    assert rating == "mid"
    assert triggered == ["fcf"]


def test_trap_rating_negative_equity_counts_as_goodwill():
    """权益 ≤ 0(资不抵债)按商誉触发处理。"""
    ctx = MockContext()
    _set_balance(ctx, "NE", GOODWILL=0, TOTAL_PARENT_EQUITY=-1e9)
    _set_healthy_cashflow(ctx, "NE")
    _set_roe_history(ctx, "NE", [15.0, 14.0, 16.0])
    rating, triggered = compute_trap_rating(ctx, "NE")
    assert "goodwill" in triggered
    assert rating in ("mid", "high")


def test_trap_rating_no_data_low():
    """所有数据缺失 → 0 触发 → low(对齐保守放行语义)。"""
    ctx = MockContext()
    rating, triggered = compute_trap_rating(ctx, "MISSING")
    assert rating == "low"
    assert triggered == []


def test_trap_rating_partial_data_low():
    """只有 balance(健康)其他缺失 → low。"""
    ctx = MockContext()
    _set_balance(ctx, "P")
    rating, triggered = compute_trap_rating(ctx, "P")
    assert rating == "low"
    assert triggered == []


# ---------- record_trap_rating ----------


def test_record_trap_rating_factors():
    """批量记录,不筛除,因子含 trap_rating + trap_triggered_count。"""
    ctx = MockContext()
    _set_balance(ctx, "OK")
    _set_healthy_cashflow(ctx, "OK")
    _set_roe_history(ctx, "OK", [15.0, 14.0, 16.0])
    _set_balance(ctx, "BAD", GOODWILL=5e8, MONETARYFUNDS=1e9, TOTAL_LIABILITIES=5e9)
    _set_bad_cashflow(ctx, "BAD")
    _set_roe_history(ctx, "BAD", [15.0, 14.0, 16.0])

    record_trap_rating(ctx, ["OK", "BAD"])

    f_ok = ctx.get_factors("OK")
    assert f_ok["trap_rating"] == "low"
    assert f_ok["trap_triggered_count"] == 0

    f_bad = ctx.get_factors("BAD")
    assert f_bad["trap_rating"] == "high"
    # GOODWILL/EQUITY=0.5 + 净现金负 + FCF 负 = 3 项
    assert f_bad["trap_triggered_count"] == 3

    # 不筛除 — 都记 log_pass
    assert "OK" in ctx.passed_symbols("conservative.trap_rating")
    assert "BAD" in ctx.passed_symbols("conservative.trap_rating")
