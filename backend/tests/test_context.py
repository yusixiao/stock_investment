import pytest
import pandas as pd
import numpy as np
from services.backtest.context import ScreenerContext, TraderContext
from services.backtest.portfolio import Portfolio


def _make_stock_data():
    n = 60
    np.random.seed(42)
    close = 10 + np.cumsum(np.random.randn(n) * 0.5)
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({
        "date": dates,
        "open": close + np.random.randn(n) * 0.1,
        "high": close + np.abs(np.random.randn(n) * 0.3),
        "low": close - np.abs(np.random.randn(n) * 0.3),
        "close": close,
        "volume": np.random.randint(1e6, 1e7, n).astype(float),
        "amount": np.random.randint(1e7, 1e8, n).astype(float),
    })
    return df


class TestScreenerContext:
    def test_get_price(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        price = ctx.get_price("600519.SH")
        assert "open" in price
        assert "close" in price
        assert "date" in price

    def test_get_price_missing_symbol(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        price = ctx.get_price("MISSING.SH")
        assert price is None

    def test_indicator_ma(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        val = ctx.indicator("600519.SH", "ma", 5)
        assert val is not None
        assert isinstance(val, float)

    def test_indicator_macd(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        dif = ctx.indicator("600519.SH", "macd", "dif")
        dea = ctx.indicator("600519.SH", "macd", "dea")
        assert dif is not None
        assert dea is not None

    def test_indicator_missing_symbol(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        val = ctx.indicator("MISSING.SH", "ma", 5)
        assert val is None

    def test_indicator_caching(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        val1 = ctx.indicator("600519.SH", "ma", 5)
        val2 = ctx.indicator("600519.SH", "ma", 5)
        assert val1 == val2

    def test_current_date(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=10)
        assert ctx.current_date == data["600519.SH"].iloc[10]["date"]

    def test_get_history(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        history = ctx.get_history("600519.SH", 5)
        assert len(history) == 5


class TestTraderContext:
    def test_has_screener_methods(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda *a: None,
            selected_symbols=["600519.SH"],
        )
        assert ctx.get_price("600519.SH") is not None
        assert ctx.current_date is not None

    def test_selected_symbols(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda *a: None,
            selected_symbols=["600519.SH"],
        )
        assert ctx.selected_symbols == ["600519.SH"]

    def test_get_portfolio(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda *a: None,
            selected_symbols=[],
        )
        p = ctx.get_portfolio()
        assert p["cash"] == 1_000_000
        assert p["total_value"] == 1_000_000

    def test_order_target_percent_generates_order(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        orders = []
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda sym, shares, d: orders.append((sym, shares, d)),
            selected_symbols=["600519.SH"],
        )
        ctx.order_target_percent("600519.SH", 0.5)
        assert len(orders) == 1
        assert orders[0][0] == "600519.SH"
        assert orders[0][2] == "buy"

    def test_rebalance_counter(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda *a: None,
            selected_symbols=[],
            days_since_rebalance=15,
        )
        assert ctx.days_since_rebalance == 15
        ctx.reset_rebalance_counter()
        assert ctx.days_since_rebalance == 0
