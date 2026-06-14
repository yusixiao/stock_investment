"""yield_factor utils 单测 — TTM 股息率计算。"""

from __future__ import annotations

import pandas as pd

from tests.utils_test_helpers import MockContext

from services.backtest.strategies.utils import yield_factor


def _ctx_with(
    divs: list[tuple[str, float]] | None,
    price: float | None,
    current_date: str = "2025-11-03",
) -> MockContext:
    dividend = {}
    if divs is not None:
        dividend["X"] = pd.DataFrame([{"date": d, "cash_dividend": c} for d, c in divs])
    price_data = {}
    if price is not None:
        price_data["X"] = {"daily": {"close": price}}
    return MockContext(dividend=dividend, price=price_data, current_date=current_date)


# ===== TTM 每股分红 =====
def test_ttm_per_share_within_window():
    ctx = _ctx_with([("2025-06-01", 1.0), ("2025-09-01", 0.5)], price=10.0)
    assert yield_factor.get_dividend_ttm_per_share(ctx, "X") == 1.5


def test_ttm_per_share_excludes_old_dates():
    """超过 365 天的派息不计入。"""
    ctx = _ctx_with(
        [("2024-01-01", 2.0), ("2025-06-01", 1.0)], price=10.0
    )  # 2024-01-01 距 2025-11-03 = 671 天,排除
    assert yield_factor.get_dividend_ttm_per_share(ctx, "X") == 1.0


def test_ttm_per_share_excludes_future_dates():
    """除权日在未来(as_of 之后)不计入。"""
    ctx = _ctx_with([("2026-01-01", 1.0), ("2025-06-01", 0.5)], price=10.0)
    assert yield_factor.get_dividend_ttm_per_share(ctx, "X") == 0.5


def test_ttm_per_share_no_dividend_data():
    ctx = _ctx_with(None, price=10.0)
    assert yield_factor.get_dividend_ttm_per_share(ctx, "X") == 0.0


def test_ttm_per_share_skips_zero_and_nan():
    ctx = _ctx_with(
        [
            ("2025-06-01", 1.0),
            ("2025-07-01", 0.0),
            ("2025-08-01", float("nan")),
            ("2025-09-01", 0.5),
        ],
        price=10.0,
    )
    assert yield_factor.get_dividend_ttm_per_share(ctx, "X") == 1.5


def test_ttm_per_share_no_current_date_returns_zero():
    ctx = _ctx_with([("2025-06-01", 1.0)], price=10.0, current_date=None)
    assert yield_factor.get_dividend_ttm_per_share(ctx, "X") == 0.0


# ===== TTM 股息率 =====
def test_yield_ttm_basic():
    ctx = _ctx_with([("2025-06-01", 1.0)], price=20.0)
    # 1.0 / 20.0 = 0.05
    assert yield_factor.get_dividend_yield_ttm(ctx, "X") == 0.05


def test_yield_ttm_zero_dividends():
    """有价格但无分红 → 0.0(零派息也是有效信号)。"""
    ctx = _ctx_with([], price=20.0)
    assert yield_factor.get_dividend_yield_ttm(ctx, "X") == 0.0


def test_yield_ttm_no_dividend_data_returns_zero():
    """股票存在但没有 dividend 表 → 0.0。"""
    ctx = _ctx_with(None, price=20.0)
    assert yield_factor.get_dividend_yield_ttm(ctx, "X") == 0.0


def test_yield_ttm_no_price_returns_none():
    ctx = _ctx_with([("2025-06-01", 1.0)], price=None)
    assert yield_factor.get_dividend_yield_ttm(ctx, "X") is None


def test_yield_ttm_zero_price_returns_none():
    ctx = _ctx_with([("2025-06-01", 1.0)], price=0.0)
    assert yield_factor.get_dividend_yield_ttm(ctx, "X") is None
