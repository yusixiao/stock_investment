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
            "date": ["2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01", "2025-01-01"],
            "open": [10.0] * 5,
            "high": [11.0] * 5,
            "low": [9.0] * 5,
            "close": [10.5] * 5,
            "volume": [1000] * 5,
            "amount": [10000] * 5,
        }),
    }


def _make_financial_data():
    return {
        "000001.SZ": pd.DataFrame({
            "报告期": ["2023-12-31", "2024-03-31", "2024-06-30", "2024-09-30"],
            "净资产收益率": [12.5, 3.2, 6.8, 10.1],
            "每股收益": [1.5, 0.4, 0.8, 1.2],
            "每股净资产": [10.0, 10.2, 10.5, 10.8],
        }),
    }


class TestGetFinancial:
    def test_returns_dict(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            financial_data=_make_financial_data(),
        )
        result = ctx.get_financial("000001.SZ")
        assert result is not None
        assert isinstance(result, dict)

    def test_returns_latest_row_before_current_date(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=2,
            financial_data=_make_financial_data(),
        )
        result = ctx.get_financial("000001.SZ")
        assert result is not None
        assert result["净资产收益率"] == 6.8

    def test_forward_fill(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=1,
            financial_data=_make_financial_data(),
        )
        result = ctx.get_financial("000001.SZ")
        assert result is not None
        assert result["净资产收益率"] == 3.2

    def test_returns_none_for_unknown_symbol(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            financial_data=_make_financial_data(),
        )
        result = ctx.get_financial("999999.SZ")
        assert result is None

    def test_returns_none_when_no_financial_data(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            financial_data={},
        )
        result = ctx.get_financial("000001.SZ")
        assert result is None

    def test_before_any_report_date(self):
        stock_data = {
            "000001.SZ": pd.DataFrame({
                "date": ["2022-01-01", "2022-06-01"],
                "open": [10.0] * 2,
                "high": [11.0] * 2,
                "low": [9.0] * 2,
                "close": [10.5] * 2,
                "volume": [1000] * 2,
                "amount": [10000] * 2,
            }),
        }
        ctx = ScreenerContext(
            stock_data=stock_data,
            current_idx=0,
            financial_data=_make_financial_data(),
        )
        result = ctx.get_financial("000001.SZ")
        assert result is None

    def test_nan_field_returns_none(self):
        fin_data = {
            "000001.SZ": pd.DataFrame({
                "报告期": ["2024-03-31"],
                "净资产收益率": [float("nan")],
                "每股收益": [0.4],
            }),
        }
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=1,
            financial_data=fin_data,
        )
        result = ctx.get_financial("000001.SZ")
        assert result is not None
        assert result["净资产收益率"] is None
        assert result["每股收益"] == 0.4


class TestTraderContextFinancial:
    def test_trader_context_has_get_financial(self):
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
            financial_data=_make_financial_data(),
        )
        result = ctx.get_financial("000001.SZ")
        assert result is not None
        assert isinstance(result, dict)
