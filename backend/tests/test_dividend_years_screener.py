import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pytest
import pandas as pd
from services.backtest.context import ScreenerContext
from dividend_years_screener import DividendYearsScreener


def _make_stock_data(symbols):
    data = {}
    for sym in symbols:
        data[sym] = pd.DataFrame({
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "open": [10.0] * 3,
            "high": [11.0] * 3,
            "low": [9.0] * 3,
            "close": [10.5] * 3,
            "volume": [1000] * 3,
            "amount": [10000] * 3,
        })
    return data


def _make_dividend_data_with_years(symbol, years_with_dividend, years_without=None):
    rows = []
    for y in years_with_dividend:
        rows.append({
            "报告期": f"{y}-12-31",
            "现金分红-现金分红比例": 3.0,
            "方案进度": "实施分配",
            "除权除息日": f"{y+1}-07-15",
        })
    for y in (years_without or []):
        rows.append({
            "报告期": f"{y}-12-31",
            "现金分红-现金分红比例": float("nan"),
            "方案进度": "实施分配",
            "除权除息日": f"{y+1}-07-15",
        })
    return {symbol: pd.DataFrame(rows)}


class TestDividendYearsScreener:
    def test_passes_with_enough_years(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        div_data = _make_dividend_data_with_years("A.SZ", [2018, 2019, 2020, 2021, 2022])
        screener = DividendYearsScreener(param_overrides={"min_years": 5})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, dividend_data=div_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result

    def test_fails_with_insufficient_years(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        div_data = _make_dividend_data_with_years("A.SZ", [2020, 2021])
        screener = DividendYearsScreener(param_overrides={"min_years": 5})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, dividend_data=div_data)
        result = screener.screen(ctx, symbols)
        assert result == []

    def test_nan_dividend_not_counted(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        div_data = _make_dividend_data_with_years("A.SZ", [2020, 2021], years_without=[2019, 2022])
        screener = DividendYearsScreener(param_overrides={"min_years": 3})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, dividend_data=div_data)
        result = screener.screen(ctx, symbols)
        assert result == []

    def test_no_dividend_data_skipped(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        screener = DividendYearsScreener(param_overrides={"min_years": 1})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, dividend_data={})
        result = screener.screen(ctx, symbols)
        assert result == []

    def test_default_min_years(self):
        screener = DividendYearsScreener()
        assert screener.p.min_years == 5

    def test_multiple_symbols(self):
        symbols = ["A.SZ", "B.SZ", "C.SZ"]
        stock_data = _make_stock_data(symbols)
        div_a = _make_dividend_data_with_years("A.SZ", [2018, 2019, 2020, 2021, 2022])
        div_b = _make_dividend_data_with_years("B.SZ", [2022])
        div_c = _make_dividend_data_with_years("C.SZ", [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022])
        div_data = {**div_a, **div_b, **div_c}
        screener = DividendYearsScreener(param_overrides={"min_years": 5})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, dividend_data=div_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result
        assert "C.SZ" in result
        assert "B.SZ" not in result

    def test_duplicate_years_counted_once(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        div_data = {
            "A.SZ": pd.DataFrame({
                "报告期": ["2020-06-30", "2020-12-31", "2021-12-31"],
                "现金分红-现金分红比例": [2.0, 3.0, 5.0],
                "方案进度": ["实施分配"] * 3,
                "除权除息日": ["2020-10-01", "2021-07-15", "2022-07-15"],
            }),
        }
        screener = DividendYearsScreener(param_overrides={"min_years": 3})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, dividend_data=div_data)
        result = screener.screen(ctx, symbols)
        assert result == []

    def test_zero_dividend_not_counted(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        div_data = {
            "A.SZ": pd.DataFrame({
                "报告期": ["2020-12-31", "2021-12-31", "2022-12-31"],
                "现金分红-现金分红比例": [3.0, 0.0, 5.0],
                "方案进度": ["实施分配"] * 3,
                "除权除息日": ["2021-07-15", "2022-07-15", "2023-07-15"],
            }),
        }
        screener = DividendYearsScreener(param_overrides={"min_years": 3})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, dividend_data=div_data)
        result = screener.screen(ctx, symbols)
        assert result == []
