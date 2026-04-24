import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pytest
import pandas as pd
from services.backtest.context import ScreenerContext
from pe_pb_product_screener import PePbProductScreener


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


def _make_valuation_data(symbol_vals):
    data = {}
    for sym, pe, pb in symbol_vals:
        data[sym] = pd.DataFrame({
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "pe_ttm": [pe] * 3,
            "pb": [pb] * 3,
            "total_mv": [100.0] * 3,
            "pe_static": [pe] * 3,
            "pcf": [1.0] * 3,
        }).sort_values("date").reset_index(drop=True)
    return data


class TestPePbProductScreener:
    def test_in_range(self):
        symbols = ["A.SZ", "B.SZ", "C.SZ"]
        stock_data = _make_stock_data(symbols)
        val_data = _make_valuation_data([
            ("A.SZ", 5.0, 2.0),
            ("B.SZ", 10.0, 3.0),
            ("C.SZ", 3.0, 1.0),
        ])
        screener = PePbProductScreener(param_overrides={"min_value": 0, "max_value": 20})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, valuation_data=val_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result
        assert "C.SZ" in result
        assert "B.SZ" not in result

    def test_negative_excluded_by_default(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        val_data = _make_valuation_data([("A.SZ", -50.0, 2.0)])
        screener = PePbProductScreener()
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, valuation_data=val_data)
        result = screener.screen(ctx, symbols)
        assert result == []

    def test_exact_boundary_included(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        val_data = _make_valuation_data([("A.SZ", 11.0, 2.0)])
        screener = PePbProductScreener(param_overrides={"min_value": 0, "max_value": 22.0})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, valuation_data=val_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result

    def test_no_valuation_skipped(self):
        symbols = ["A.SZ", "B.SZ"]
        stock_data = _make_stock_data(symbols)
        val_data = _make_valuation_data([("A.SZ", 5.0, 2.0)])
        screener = PePbProductScreener(param_overrides={"min_value": 0, "max_value": 20})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, valuation_data=val_data)
        result = screener.screen(ctx, symbols)
        assert "A.SZ" in result
        assert "B.SZ" not in result

    def test_nan_pe_skipped(self):
        symbols = ["A.SZ"]
        stock_data = _make_stock_data(symbols)
        val_data = {
            "A.SZ": pd.DataFrame({
                "date": ["2024-01-01"],
                "pe_ttm": [float("nan")],
                "pb": [0.5],
                "total_mv": [100.0],
                "pe_static": [float("nan")],
                "pcf": [1.0],
            }).sort_values("date").reset_index(drop=True),
        }
        screener = PePbProductScreener()
        ctx = ScreenerContext(stock_data=stock_data, current_idx=0, valuation_data=val_data)
        result = screener.screen(ctx, symbols)
        assert result == []

    def test_default_params(self):
        screener = PePbProductScreener()
        assert screener.p.min_value == 0.0
        assert screener.p.max_value == 22.0

    def test_custom_range(self):
        symbols = ["A.SZ", "B.SZ"]
        stock_data = _make_stock_data(symbols)
        val_data = _make_valuation_data([
            ("A.SZ", 5.0, 2.0),
            ("B.SZ", 10.0, 3.0),
        ])
        screener = PePbProductScreener(param_overrides={"min_value": 15, "max_value": 35})
        ctx = ScreenerContext(stock_data=stock_data, current_idx=2, valuation_data=val_data)
        result = screener.screen(ctx, symbols)
        assert "B.SZ" in result
        assert "A.SZ" not in result
