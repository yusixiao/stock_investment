import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
from services.backtest.context import ScreenerContext, TraderContext
from services.backtest.portfolio import Portfolio


def _make_stock_data():
    return {
        "000001.SZ": pd.DataFrame({
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
            "open": [10.0] * 5,
            "high": [11.0] * 5,
            "low": [9.0] * 5,
            "close": [10.5] * 5,
            "volume": [1000] * 5,
            "amount": [10000] * 5,
        }),
    }


def _make_dividend_data():
    return {
        "000001.SZ": pd.DataFrame({
            "报告期": ["2020-12-31", "2021-12-31", "2022-12-31", "2023-06-30"],
            "现金分红-现金分红比例": [3.0, 5.0, float("nan"), 2.0],
            "方案进度": ["实施分配", "实施分配", "实施分配", "实施分配"],
            "除权除息日": ["2021-07-15", "2022-07-20", "2023-07-10", "2023-12-01"],
        }),
    }


class TestGetDividend:
    def test_returns_dataframe(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            dividend_data=_make_dividend_data(),
        )
        result = ctx.get_dividend("000001.SZ")
        assert result is not None
        assert isinstance(result, pd.DataFrame)

    def test_returns_none_for_unknown_symbol(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            dividend_data=_make_dividend_data(),
        )
        result = ctx.get_dividend("999999.SZ")
        assert result is None

    def test_returns_none_when_no_dividend_data(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            dividend_data={},
        )
        result = ctx.get_dividend("000001.SZ")
        assert result is None

    def test_returns_all_rows(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            dividend_data=_make_dividend_data(),
        )
        result = ctx.get_dividend("000001.SZ")
        assert len(result) == 4

    def test_columns_preserved(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            dividend_data=_make_dividend_data(),
        )
        result = ctx.get_dividend("000001.SZ")
        assert "报告期" in result.columns
        assert "现金分红-现金分红比例" in result.columns


class TestTraderContextDividend:
    def test_trader_context_has_get_dividend(self):
        stock_data = _make_stock_data()
        for sym in stock_data:
            stock_data[sym] = stock_data[sym].sort_values("date").reset_index(drop=True)
        portfolio = Portfolio(initial_capital=100000)
        ctx = TraderContext(
            stock_data=stock_data,
            current_idx=0,
            portfolio=portfolio,
            broker_submit=lambda *a: None,
            selected_symbols=["000001.SZ"],
            dividend_data=_make_dividend_data(),
        )
        result = ctx.get_dividend("000001.SZ")
        assert result is not None
        assert isinstance(result, pd.DataFrame)
