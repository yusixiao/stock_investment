"""balance_long utils 单测 — NOTICE_DATE 严格 PIT 负债率历史 / 去杠杆信号。

关键验证点:
1. PIT:NOTICE_DATE > current_date 的年报不得泄漏(消除 REPORT_DATE as-of 前视)。
2. REPORT_DATE 去重:同财年重述(两个 NOTICE_DATE)不污染 YoY 比较。
3. 负债率回退:TOTAL_LIABILITIES/TOTAL_ASSETS 缺失时回退 DEBT_ASSET_RATIO/100。
4. is_deleveraging 的 min_drop 幅度门槛。
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.utils_test_helpers import MockContext

from services.backtest.strategies.utils import balance_long


def _inject(rows: list[dict], code: str = "X", market: str = "A") -> None:
    """把年报行注入模块级 PIT 缓存(绕过 DuckDB)。rows 需含 NOTICE_DATE/REPORT_DATE。"""
    df = pd.DataFrame(rows)
    df["NOTICE_DATE"] = df["NOTICE_DATE"].astype(str)
    df["REPORT_DATE"] = df["REPORT_DATE"].astype(str)
    df = df.sort_values("NOTICE_DATE").reset_index(drop=True)
    balance_long._BAL_HIST[market] = {code: df}


@pytest.fixture(autouse=True)
def _clear_cache():
    balance_long.reset_balance_cache()
    yield
    balance_long.reset_balance_cache()


def _row(notice: str, report: str, liab, assets, dar=None) -> dict:
    return {
        "NOTICE_DATE": notice,
        "REPORT_DATE": report,
        "TOTAL_LIABILITIES": liab,
        "TOTAL_ASSETS": assets,
        "DEBT_ASSET_RATIO": dar,
    }


# ===== get_debt_ratios 基础 =====
def test_debt_ratios_ascending_fraction():
    _inject(
        [
            _row("2022-04-01", "2021-12-31", 80.0, 100.0),  # 0.80
            _row("2023-04-01", "2022-12-31", 70.0, 100.0),  # 0.70
            _row("2024-04-01", "2023-12-31", 60.0, 100.0),  # 0.60
        ]
    )
    ctx = MockContext(current_date="2024-06-01")
    ratios = balance_long.get_debt_ratios(ctx, "X", n_years=3)
    assert ratios == pytest.approx([0.80, 0.70, 0.60])  # 升序,[-1]=最新


def test_debt_ratios_insufficient_history_returns_none():
    _inject([_row("2024-04-01", "2023-12-31", 60.0, 100.0)])
    ctx = MockContext(current_date="2024-06-01")
    assert balance_long.get_debt_ratios(ctx, "X", n_years=2) is None


def test_debt_ratios_unknown_symbol_returns_none():
    _inject([_row("2024-04-01", "2023-12-31", 60.0, 100.0)])
    ctx = MockContext(current_date="2024-06-01")
    assert balance_long.get_debt_ratios(ctx, "NOPE", n_years=1) is None


# ===== PIT:未披露年报不得泄漏 =====
def test_pit_excludes_undisclosed_report():
    _inject(
        [
            _row("2023-04-01", "2022-12-31", 70.0, 100.0),  # 0.70
            _row("2024-04-30", "2023-12-31", 60.0, 100.0),  # 0.60,NOTICE 晚于决策日
        ]
    )
    # 决策日 2024-03-01:2023 年报(NOTICE 2024-04-30)尚未披露,只能看到 0.70
    ctx = MockContext(current_date="2024-03-01")
    ratios = balance_long.get_debt_ratios(ctx, "X", n_years=1)
    assert ratios == pytest.approx([0.70])
    # 且此时不足 2 年 → 去杠杆无法判断
    assert balance_long.is_deleveraging(ctx, "X") is None


def test_pit_includes_after_disclosure():
    _inject(
        [
            _row("2023-04-01", "2022-12-31", 70.0, 100.0),
            _row("2024-04-30", "2023-12-31", 60.0, 100.0),
        ]
    )
    # 决策日 2024-06-01:两份都已披露
    ctx = MockContext(current_date="2024-06-01")
    ratios = balance_long.get_debt_ratios(ctx, "X", n_years=2)
    assert ratios == pytest.approx([0.70, 0.60])


# ===== REPORT_DATE 去重:重述不污染 YoY =====
def test_restatement_dedup_keeps_distinct_fiscal_years():
    _inject(
        [
            _row("2023-04-01", "2022-12-31", 70.0, 100.0),  # 2022 原始
            _row("2024-04-01", "2023-12-31", 62.0, 100.0),  # 2023 原始
            _row("2024-08-01", "2023-12-31", 60.0, 100.0),  # 2023 重述(更新披露)
        ]
    )
    ctx = MockContext(current_date="2024-10-01")
    ratios = balance_long.get_debt_ratios(ctx, "X", n_years=2)
    # 只应有 2 个不同财年:2022(0.70) + 2023 重述后(0.60),不是两条 2023
    assert ratios == pytest.approx([0.70, 0.60])


# ===== DEBT_ASSET_RATIO 回退 =====
def test_fallback_to_debt_asset_ratio_when_liab_missing():
    _inject(
        [
            _row("2023-04-01", "2022-12-31", None, None, dar=75.0),  # 0.75
            _row("2024-04-01", "2023-12-31", None, None, dar=65.0),  # 0.65
        ]
    )
    ctx = MockContext(current_date="2024-06-01")
    ratios = balance_long.get_debt_ratios(ctx, "X", n_years=2)
    assert ratios == pytest.approx([0.75, 0.65])


def test_missing_both_returns_none():
    _inject([_row("2024-04-01", "2023-12-31", None, None, dar=None)])
    ctx = MockContext(current_date="2024-06-01")
    assert balance_long.get_debt_ratios(ctx, "X", n_years=1) is None


# ===== is_deleveraging =====
def test_is_deleveraging_true_on_decline():
    _inject(
        [
            _row("2023-04-01", "2022-12-31", 70.0, 100.0),
            _row("2024-04-01", "2023-12-31", 60.0, 100.0),
        ]
    )
    ctx = MockContext(current_date="2024-06-01")
    assert balance_long.is_deleveraging(ctx, "X") is True


def test_is_deleveraging_false_on_rise():
    _inject(
        [
            _row("2023-04-01", "2022-12-31", 60.0, 100.0),
            _row("2024-04-01", "2023-12-31", 70.0, 100.0),
        ]
    )
    ctx = MockContext(current_date="2024-06-01")
    assert balance_long.is_deleveraging(ctx, "X") is False


def test_is_deleveraging_min_drop_threshold():
    _inject(
        [
            _row("2023-04-01", "2022-12-31", 71.0, 100.0),  # 0.71
            _row("2024-04-01", "2023-12-31", 70.0, 100.0),  # 0.70,仅降 1pct
        ]
    )
    ctx = MockContext(current_date="2024-06-01")
    # 降幅 0.01 < min_drop 0.02 → False
    assert balance_long.is_deleveraging(ctx, "X", min_drop=0.02) is False
    # 只要下降即可 → True
    assert balance_long.is_deleveraging(ctx, "X", min_drop=0.0) is True


def test_get_latest_debt_ratio():
    _inject(
        [
            _row("2023-04-01", "2022-12-31", 70.0, 100.0),
            _row("2024-04-01", "2023-12-31", 55.0, 100.0),
        ]
    )
    ctx = MockContext(current_date="2024-06-01")
    assert balance_long.get_latest_debt_ratio(ctx, "X") == pytest.approx(0.55)
