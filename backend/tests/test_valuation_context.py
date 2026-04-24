import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
import math
from services.backtest.context import ScreenerContext


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


def _make_valuation_data():
    return {
        "000001.SZ": pd.DataFrame({
            "date": ["2024-01-01", "2024-01-03", "2024-01-05"],
            "pe_ttm": [5.0, 6.0, 7.0],
            "pb": [0.5, 0.6, 0.7],
            "total_mv": [100.0, 110.0, 120.0],
            "pe_static": [4.5, 5.5, 6.5],
            "pcf": [1.0, 1.1, 1.2],
        }).sort_values("date").reset_index(drop=True),
    }


class TestGetValuation:
    def test_exact_date_match(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=2,
            valuation_data=_make_valuation_data(),
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is not None
        assert val["pe_ttm"] == 6.0
        assert val["pb"] == 0.6

    def test_forward_fill_between_dates(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=1,
            valuation_data=_make_valuation_data(),
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is not None
        assert val["pe_ttm"] == 5.0
        assert val["pb"] == 0.5

    def test_latest_available(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=3,
            valuation_data=_make_valuation_data(),
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is not None
        assert val["pe_ttm"] == 6.0
        assert val["pb"] == 0.6

    def test_no_valuation_data(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            valuation_data={},
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is None

    def test_unknown_symbol(self):
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            valuation_data=_make_valuation_data(),
        )
        val = ctx.get_valuation("999999.SZ")
        assert val is None

    def test_nan_fallback_to_previous(self):
        val_data = {
            "000001.SZ": pd.DataFrame({
                "date": ["2024-01-01", "2024-01-03"],
                "pe_ttm": [5.0, float("nan")],
                "pb": [0.5, 0.6],
                "total_mv": [100.0, float("nan")],
                "pe_static": [4.5, float("nan")],
                "pcf": [1.0, float("nan")],
            }).sort_values("date").reset_index(drop=True),
        }
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=2,
            valuation_data=val_data,
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is not None
        assert val["pe_ttm"] == 5.0
        assert val["pb"] == 0.6

    def test_all_nan_returns_none_for_field(self):
        val_data = {
            "000001.SZ": pd.DataFrame({
                "date": ["2024-01-01"],
                "pe_ttm": [float("nan")],
                "pb": [float("nan")],
                "total_mv": [float("nan")],
                "pe_static": [float("nan")],
                "pcf": [float("nan")],
            }).sort_values("date").reset_index(drop=True),
        }
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=0,
            valuation_data=val_data,
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is not None
        assert val["pe_ttm"] is None
        assert val["pb"] is None

    def test_before_any_valuation_date(self):
        stock_data = {
            "000001.SZ": pd.DataFrame({
                "date": ["2023-12-01", "2023-12-02"],
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
            valuation_data=_make_valuation_data(),
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is None


    def test_datetime_date_type_in_valuation(self):
        from datetime import date as _date
        val_data = {
            "000001.SZ": pd.DataFrame({
                "date": [_date(2024, 1, 1), _date(2024, 1, 3)],
                "pe_ttm": [5.0, 6.0],
                "pb": [0.5, 0.6],
                "total_mv": [100.0, 110.0],
                "pe_static": [4.5, 5.5],
                "pcf": [1.0, 1.1],
            }).sort_values("date").reset_index(drop=True),
        }
        ctx = ScreenerContext(
            stock_data=_make_stock_data(),
            current_idx=2,
            valuation_data=val_data,
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is not None
        assert val["pe_ttm"] == 6.0
        assert val["pb"] == 0.6


class TestGetValuationMonthly:
    def test_monthly_frequency_uses_current_date(self):
        stock_data = {
            "000001.SZ": pd.DataFrame({
                "date": ["2024-01-31", "2024-02-29", "2024-03-31"],
                "open": [10.0] * 3,
                "high": [11.0] * 3,
                "low": [9.0] * 3,
                "close": [10.5] * 3,
                "volume": [1000] * 3,
                "amount": [10000] * 3,
            }),
        }
        val_data = {
            "000001.SZ": pd.DataFrame({
                "date": ["2024-01-15", "2024-02-20", "2024-03-10"],
                "pe_ttm": [5.0, 6.0, 7.0],
                "pb": [0.5, 0.6, 0.7],
                "total_mv": [100.0, 110.0, 120.0],
                "pe_static": [4.5, 5.5, 6.5],
                "pcf": [1.0, 1.1, 1.2],
            }).sort_values("date").reset_index(drop=True),
        }
        monthly_data = {
            "000001.SZ": pd.DataFrame({
                "date": ["2024-01-31", "2024-02-29", "2024-03-31"],
                "open": [10.0] * 3,
                "high": [11.0] * 3,
                "low": [9.0] * 3,
                "close": [10.5] * 3,
                "volume": [1000] * 3,
                "amount": [10000] * 3,
            }),
        }
        ctx = ScreenerContext(
            stock_data=stock_data,
            current_idx=1,
            frequency="monthly",
            monthly_data=monthly_data,
            valuation_data=val_data,
        )
        val = ctx.get_valuation("000001.SZ")
        assert val is not None
        assert val["pe_ttm"] == 6.0
        assert val["pb"] == 0.6
