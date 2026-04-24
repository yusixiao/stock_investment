import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pytest
import pandas as pd
from services.backtest.context import ScreenerContext
from roe_screener import RoeScreener


def _make_stock_data(symbols):
    data = {}
    for sym in symbols:
        data[sym] = pd.DataFrame({
            "date": ["2024-01-01", "2024-04-01", "2024-07-01"],
            "open": [10.0] * 3,
            "high": [11.0] * 3,
            "low": [9.0] * 3,
            "close": [10.5] * 3,
            "volume": [1000] * 3,
            "amount": [10000] * 3,
        })
    return data


def _make_financial_data(symbol_roe_map):
    data = {}
    for sym, roe in symbol_roe_map.items():
        data[sym] = pd.DataFrame({
            "报告期": ["2024-03-31"],
            "净资产收益率": [roe],
            "每股收益": [1.0],
            "每股净资产": [10.0],
        })
    return data


class TestRoeScreener:
    def test_passes_above_threshold(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        fin_data = _make_financial_data({"A.SZ": 15.0})
        screener = RoeScreener(param_overrides={"min_roe": 10})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=1, financial_data=fin_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result

    def test_fails_below_threshold(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        fin_data = _make_financial_data({"A.SZ": 5.0})
        screener = RoeScreener(param_overrides={"min_roe": 10})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=1, financial_data=fin_data)
        result = screener.screen(ctx, symbols)
        assert result == []

    def test_exact_boundary_included(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        fin_data = _make_financial_data({"A.SZ": 10.0})
        screener = RoeScreener(param_overrides={"min_roe": 10})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=1, financial_data=fin_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result

    def test_default_min_roe(self):
        screener = RoeScreener()
        assert screener.p.min_roe == 10

    def test_multiple_symbols(self):
        symbols = ["A.SZ", "B.SZ", "C.SZ"]
        stock_data = _make_stock_data(symbols)
        fin_data = _make_financial_data({"A.SZ": 15.0, "B.SZ": 5.0, "C.SZ": 12.0})
        screener = RoeScreener(param_overrides={"min_roe": 10})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=1, financial_data=fin_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result
        assert "C.SZ" in result
        assert "B.SZ" not in result

    def test_no_financial_data_skipped(self):
        symbols = ["A.SZ", "B.SZ"]
        stock_data = _make_stock_data(symbols)
        fin_data = _make_financial_data({"A.SZ": 15.0})
        screener = RoeScreener(param_overrides={"min_roe": 10})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=1, financial_data=fin_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result
        assert "B.SZ" not in result

    def test_nan_roe_skipped(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        fin_data = _make_financial_data({"A.SZ": float("nan")})
        screener = RoeScreener(param_overrides={"min_roe": 10})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=1, financial_data=fin_data)
        result = screener.screen(ctx, symbols)
        assert result == []
