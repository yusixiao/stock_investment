"""现金流保守粗算策略 utils 单测(strategies/utils/conservative.py)。

口径基于 cpa Phase 3.1 Step 10 因子2 R(粗算穿透回报率):
    R = NP × M × (1 − Q) / 市值

⚠️ 边界:本模块只实现 cpa 框架的"粗算 R",**不**实现需要 LLM 11 步精算的真实 GG / KK。
门槛 II 与税率 Q 来自 references/shared_tables.md。
"""

from __future__ import annotations

import pandas as pd

from tests.utils_test_helpers import MockContext

from strategies.utils.conservative import (
    RF_CHINA_10Y,
    THRESHOLD_A_PCT,
    compute_payout_ratio_3y,
    compute_r,
    filter_by_r,
    reject_financial_industry,
    reject_high_goodwill,
    reject_low_fcf_yield,
    reject_negative_fcf_2y,
    reject_negative_net_cash,
)


# ---------- 常量 ----------


def test_constants_match_shared_tables():
    """RF_CHINA_10Y 与 cpa §14 一致;A 股门槛 II = max(3.5%, Rf+2%) = 4.7%。"""
    assert RF_CHINA_10Y == 0.027
    assert THRESHOLD_A_PCT == 4.7


# ---------- compute_payout_ratio_3y ----------


def _set_3y_history(ctx, sym, eps_list, dps_list):
    """便捷:按 3 个年报(最新→最旧)铺 EPSJB + dividend(每年单条 cash_dividend)。"""
    ctx.set_financial_history(
        {
            sym: [
                {"REPORT_DATE": f"{2023 - i}-12-31", "EPSJB": eps_list[i]}
                for i in range(3)
            ]
        }
    )
    rows = []
    for i in range(3):
        year = 2023 - i
        rows.append({"date": f"{year}-06-30", "cash_dividend": dps_list[i]})
    ctx._dividend[sym] = pd.DataFrame(rows)


def test_payout_ratio_3y_happy_path():
    """近 3 年 EPS=[2,1.5,1],DPS=[1,0.6,0.4] → 支付率 [0.5,0.4,0.4],均值 ≈ 0.433。"""
    ctx = MockContext()
    _set_3y_history(ctx, "TEST", eps_list=[2.0, 1.5, 1.0], dps_list=[1.0, 0.6, 0.4])
    m = compute_payout_ratio_3y(ctx, "TEST")
    assert m is not None
    assert abs(m - (0.5 + 0.4 + 0.4) / 3) < 1e-6


def test_payout_ratio_3y_no_dividend_returns_none():
    ctx = MockContext()
    _set_3y_history(ctx, "TEST", eps_list=[1, 1, 1], dps_list=[0, 0, 0])
    assert compute_payout_ratio_3y(ctx, "TEST") is None


def test_payout_ratio_3y_loss_year_returns_none():
    """近 3 年累计 EPS ≤ 0 → 亏损公司,M 不可计算。"""
    ctx = MockContext()
    _set_3y_history(ctx, "TEST", eps_list=[-1, -2, -3], dps_list=[0.1, 0.1, 0.1])
    assert compute_payout_ratio_3y(ctx, "TEST") is None


def test_payout_ratio_3y_missing_history_returns_none():
    ctx = MockContext()
    assert compute_payout_ratio_3y(ctx, "MISSING") is None


# ---------- compute_r ----------


def _setup_r_data(ctx, sym, *, np_value, eps_list, dps_list, total_share, close_price):
    """铺设 compute_r 全套数据:financial_annual(NP / TOTAL_SHARE)+ history + price。"""
    ctx._financial[sym] = {
        "PARENTNETPROFIT": np_value,
        "TOTAL_SHARE": total_share,
    }
    _set_3y_history(ctx, sym, eps_list, dps_list)
    ctx._price[sym] = {"daily": {"close": close_price}}


def test_compute_r_a_share_happy_path():
    """A 股口径(Q=0):NP=10亿,M=0.5,股本 1亿,价 50 → 市值 50 亿,R = 10 × 0.5 / 50 = 10%。"""
    ctx = MockContext()
    _setup_r_data(
        ctx,
        "A",
        np_value=1_000_000_000,
        eps_list=[1.0, 1.0, 1.0],
        dps_list=[0.5, 0.5, 0.5],  # 支付率 0.5
        total_share=100_000_000,
        close_price=50.0,
    )
    r = compute_r(ctx, "A")
    assert r is not None
    assert abs(r - 10.0) < 0.01  # 10%


def test_compute_r_zero_or_negative_np_returns_none():
    ctx = MockContext()
    _setup_r_data(
        ctx,
        "B",
        np_value=-100,
        eps_list=[1, 1, 1],
        dps_list=[0.5, 0.5, 0.5],
        total_share=100_000_000,
        close_price=50.0,
    )
    assert compute_r(ctx, "B") is None


def test_compute_r_missing_payout_returns_none():
    ctx = MockContext()
    ctx._financial["X"] = {"PARENTNETPROFIT": 1e9, "TOTAL_SHARE": 1e8}
    ctx._price["X"] = {"daily": {"close": 50}}
    # 没设 history → 支付率不可算
    assert compute_r(ctx, "X") is None


def test_compute_r_missing_price_returns_none():
    ctx = MockContext()
    _setup_r_data(
        ctx,
        "Y",
        np_value=1e9,
        eps_list=[1, 1, 1],
        dps_list=[0.5, 0.5, 0.5],
        total_share=1e8,
        close_price=50,
    )
    ctx._price.pop("Y")
    assert compute_r(ctx, "Y") is None


# ---------- filter_by_r ----------


def test_filter_by_r_threshold():
    """门槛默认 4.7+0.5=5.2pct,符合的留下,不达标的 reject。"""
    ctx = MockContext()
    # high R: NP=1e9,M=0.5,share=1e8,close=50 → R=10pct
    _setup_r_data(
        ctx,
        "HIGH",
        np_value=1e9,
        eps_list=[1, 1, 1],
        dps_list=[0.5, 0.5, 0.5],
        total_share=1e8,
        close_price=50,
    )
    # low R: 同 NP/M,但市值翻 4 倍 (close=200) → R=2.5pct
    _setup_r_data(
        ctx,
        "LOW",
        np_value=1e9,
        eps_list=[1, 1, 1],
        dps_list=[0.5, 0.5, 0.5],
        total_share=1e8,
        close_price=200,
    )
    out = filter_by_r(ctx, ["HIGH", "LOW"])
    assert out == ["HIGH"]
    assert "HIGH" in ctx.passed_symbols("conservative.r")
    assert "LOW" in ctx.rejected_symbols("conservative.r")


def test_filter_by_r_records_factor():
    ctx = MockContext()
    _setup_r_data(
        ctx,
        "X",
        np_value=1e9,
        eps_list=[1, 1, 1],
        dps_list=[0.5, 0.5, 0.5],
        total_share=1e8,
        close_price=50,
    )
    filter_by_r(ctx, ["X"])
    assert "R_pct" in ctx.get_factors("X")
    assert abs(ctx.get_factors("X")["R_pct"] - 10.0) < 0.01


# ---------- reject_financial_industry ----------


def test_reject_financial_industry():
    ctx = MockContext()
    ctx.set_balance(
        {
            "BANK": {"INDUSTRY_NAME": "银行"},
            "INSURE": {"INDUSTRY_NAME": "保险"},
            "BROKER": {"INDUSTRY_NAME": "证券"},
            "TECH": {"INDUSTRY_NAME": "电子"},
            "UNKNOWN": {},  # 行业缺失 → 放行(避免误杀)
        }
    )
    out = reject_financial_industry(
        ctx, ["BANK", "INSURE", "BROKER", "TECH", "UNKNOWN"]
    )
    assert set(out) == {"TECH", "UNKNOWN"}


# ---------- reject_high_goodwill ----------


def test_reject_high_goodwill():
    ctx = MockContext()
    ctx.set_balance(
        {
            "GOOD": {"GOODWILL": 1e8, "TOTAL_PARENT_EQUITY": 1e9},  # 10% 通过
            "BAD": {"GOODWILL": 5e8, "TOTAL_PARENT_EQUITY": 1e9},  # 50% 否决
            "ZERO_GW": {"GOODWILL": 0, "TOTAL_PARENT_EQUITY": 1e9},  # 0% 通过
            "NO_DATA": {},  # 数据缺失:保守放行
        }
    )
    out = reject_high_goodwill(ctx, ["GOOD", "BAD", "ZERO_GW", "NO_DATA"])
    assert set(out) == {"GOOD", "ZERO_GW", "NO_DATA"}


def test_reject_high_goodwill_zero_equity_rejects():
    """归母权益 ≤ 0(资不抵债)→ 直接否决,不做除法。"""
    ctx = MockContext()
    ctx.set_balance({"BANKRUPT": {"GOODWILL": 1, "TOTAL_PARENT_EQUITY": 0}})
    assert reject_high_goodwill(ctx, ["BANKRUPT"]) == []


# ---------- reject_negative_net_cash ----------


def test_reject_negative_net_cash():
    ctx = MockContext()
    ctx.set_balance(
        {
            "STRONG": {"MONETARYFUNDS": 5e9, "TOTAL_LIABILITIES": 1e9},  # +4e9 通过
            "WEAK": {"MONETARYFUNDS": 1e9, "TOTAL_LIABILITIES": 5e9},  # -4e9 否决
            "BREAK_EVEN": {"MONETARYFUNDS": 1e9, "TOTAL_LIABILITIES": 1e9},  # 0 通过
            "NO_DATA": {},  # 缺失:保守放行
        }
    )
    out = reject_negative_net_cash(ctx, ["STRONG", "WEAK", "BREAK_EVEN", "NO_DATA"])
    assert set(out) == {"STRONG", "BREAK_EVEN", "NO_DATA"}


# ---------- reject_negative_fcf_2y ----------


def test_reject_negative_fcf_2y_both_negative_rejected():
    ctx = MockContext()
    ctx.set_cashflow_history(
        {
            "BAD": [
                {
                    "REPORT_DATE": "2023-12-31",
                    "NETCASH_OPERATE": 1e8,
                    "CONSTRUCT_LONG_ASSET": 2e8,
                },  # FCF=-1e8
                {
                    "REPORT_DATE": "2022-12-31",
                    "NETCASH_OPERATE": 5e7,
                    "CONSTRUCT_LONG_ASSET": 1e8,
                },  # FCF=-5e7
            ]
        }
    )
    assert reject_negative_fcf_2y(ctx, ["BAD"]) == []


def test_reject_negative_fcf_2y_one_positive_passes():
    """只要近2年里有 1 年 FCF > 0 就通过(避免单年异常误杀)。"""
    ctx = MockContext()
    ctx.set_cashflow_history(
        {
            "OK": [
                {
                    "REPORT_DATE": "2023-12-31",
                    "NETCASH_OPERATE": 5e8,
                    "CONSTRUCT_LONG_ASSET": 1e8,
                },  # FCF=4e8
                {
                    "REPORT_DATE": "2022-12-31",
                    "NETCASH_OPERATE": 1e8,
                    "CONSTRUCT_LONG_ASSET": 2e8,
                },  # FCF=-1e8
            ]
        }
    )
    assert reject_negative_fcf_2y(ctx, ["OK"]) == ["OK"]


def test_reject_negative_fcf_2y_missing_history_passes():
    """history 不可达 → 保守放行。"""
    ctx = MockContext()
    assert reject_negative_fcf_2y(ctx, ["MISSING"]) == ["MISSING"]


# ---------- reject_low_fcf_yield ----------


def test_reject_low_fcf_yield_below_threshold_rejected():
    """FCF yield < 5% → 拒。FCF=1e7,market_cap=1e9 → yield=1% < 5%。"""
    ctx = MockContext(
        price={"BAD": {"daily": {"close": 10.0}}},
    )
    ctx.set_cashflow({"BAD": {"NETCASH_OPERATE": 2e7, "CONSTRUCT_LONG_ASSET": 1e7}})
    ctx.set_financial({"BAD": {"TOTAL_SHARE": 1e8}})  # market_cap = 10 × 1e8 = 1e9
    assert reject_low_fcf_yield(ctx, ["BAD"]) == []


def test_reject_low_fcf_yield_above_threshold_passes():
    """FCF yield ≥ 5% → 通过。FCF=8e7,market_cap=1e9 → yield=8%。"""
    ctx = MockContext(
        price={"OK": {"daily": {"close": 10.0}}},
    )
    ctx.set_cashflow({"OK": {"NETCASH_OPERATE": 1e8, "CONSTRUCT_LONG_ASSET": 2e7}})
    ctx.set_financial({"OK": {"TOTAL_SHARE": 1e8}})
    assert reject_low_fcf_yield(ctx, ["OK"]) == ["OK"]


def test_reject_low_fcf_yield_missing_data_passes():
    """cashflow / financial / price 任一不可达 → 保守放行。"""
    ctx = MockContext()
    assert reject_low_fcf_yield(ctx, ["MISSING"]) == ["MISSING"]


def test_reject_low_fcf_yield_negative_fcf_rejected():
    """负 FCF 必然 < 5% threshold → 拒。"""
    ctx = MockContext(
        price={"NEG": {"daily": {"close": 10.0}}},
    )
    ctx.set_cashflow({"NEG": {"NETCASH_OPERATE": 1e7, "CONSTRUCT_LONG_ASSET": 5e7}})
    ctx.set_financial({"NEG": {"TOTAL_SHARE": 1e8}})
    assert reject_low_fcf_yield(ctx, ["NEG"]) == []


def test_reject_low_fcf_yield_custom_threshold():
    """支持自定义阈值。"""
    ctx = MockContext(
        price={"X": {"daily": {"close": 10.0}}},
    )
    ctx.set_cashflow({"X": {"NETCASH_OPERATE": 4e7, "CONSTRUCT_LONG_ASSET": 0}})
    ctx.set_financial({"X": {"TOTAL_SHARE": 1e8}})  # yield=4%
    assert reject_low_fcf_yield(ctx, ["X"], threshold=0.03) == ["X"]
    assert reject_low_fcf_yield(ctx, ["X"], threshold=0.05) == []
