import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from services.backtest.engine import BacktestEngine
from services.backtest.base import ScreenerStrategy, TraderStrategy


def _make_stock_df(n=100, seed=42, base_price=100.0):
    np.random.seed(seed)
    close = base_price + np.cumsum(np.random.randn(n) * 1.0)
    close = np.maximum(close, 1.0)
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    return pd.DataFrame({
        "date": dates,
        "open": close + np.random.randn(n) * 0.5,
        "high": close + np.abs(np.random.randn(n) * 1.0),
        "low": close - np.abs(np.random.randn(n) * 1.0),
        "close": close,
        "volume": np.random.randint(1e6, 1e7, n).astype(float),
        "amount": np.random.randint(1e7, 1e8, n).astype(float),
    })


class AlwaysPassScreener(ScreenerStrategy):
    name = "pass-all"
    description = ""
    params = {}

    def screen(self, ctx, symbols):
        return symbols


class TopOneScreener(ScreenerStrategy):
    name = "top-one"
    description = ""
    params = {}

    def screen(self, ctx, symbols):
        return symbols[:1]


class BuyAndHoldTrader(TraderStrategy):
    name = "buy-hold"
    description = ""
    params = {}
    settings = {"initial_capital": 100_000, "commission_rate": 0.0003, "slippage": 0.0}

    def on_bar(self, ctx):
        for sym in ctx.selected_symbols:
            if not ctx.get_position(sym):
                ctx.order_target_percent(sym, 0.9)


class TestBacktestEngine:
    def _make_data(self):
        return {
            "AAA.SH": _make_stock_df(100, seed=42, base_price=50.0),
            "BBB.SZ": _make_stock_df(100, seed=43, base_price=100.0),
        }

    def test_screener_only_returns_symbols(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=None,
        )
        result = engine.run()
        assert "screened_symbols" in result
        assert len(result["screened_symbols"]) > 0

    def test_screener_chain(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), TopOneScreener()],
            trader=None,
        )
        result = engine.run()
        assert len(result["screened_symbols"]) == 1

    def test_screener_backtest_returns_match_dates(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=None,
        )
        result = engine.run()
        assert "screened_symbols" in result
        assert len(result["screened_symbols"]) > 0
        item = result["screened_symbols"][0]
        assert "symbol" in item
        assert "match_dates" in item
        assert len(item["match_dates"]) > 0

    def test_screener_only_mode(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=None,
        )
        result = engine.run(mode="screen")
        assert "screened_symbols" in result
        assert isinstance(result["screened_symbols"][0], str)

    def test_full_backtest_returns_metrics(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        assert "metrics" in result
        assert "total_return" in result["metrics"]
        assert "equity_curve" in result
        assert "trades" in result

    def test_equity_curve_has_entries(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        assert len(result["equity_curve"]) > 0
        assert "date" in result["equity_curve"][0]
        assert "total_value" in result["equity_curve"][0]

    def test_trades_have_correct_fields(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        if result["trades"]:
            t = result["trades"][0]
            assert "date" in t
            assert "symbol" in t
            assert "direction" in t
            assert "price" in t
            assert "shares" in t

    def test_empty_screener_result(self):
        class EmptyScreener(ScreenerStrategy):
            name = "empty"
            description = ""
            params = {}
            def screen(self, ctx, symbols):
                return []

        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[EmptyScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        assert result["trades"] == []
