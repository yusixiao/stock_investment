import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from services.backtest.engine import BacktestEngine
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.date_utils import detect_frequency


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


class OddMonthScreener(ScreenerStrategy):
    name = "odd-month"
    description = ""
    params = {}
    frequency = "monthly"

    def screen(self, ctx, symbols):
        month = int(ctx.current_date[5:7])
        if month % 2 == 1:
            return symbols
        return []


class EvenMonthScreener(ScreenerStrategy):
    name = "even-month"
    description = ""
    params = {}
    frequency = "monthly"

    def screen(self, ctx, symbols):
        month = int(ctx.current_date[5:7])
        if month % 2 == 0:
            return symbols
        return []


class FirstHalfScreener(ScreenerStrategy):
    name = "first-half"
    description = ""
    params = {}
    frequency = "daily"

    def screen(self, ctx, symbols):
        mid = max(1, len(symbols) // 2)
        return symbols[:mid]


class SecondHalfScreener(ScreenerStrategy):
    name = "second-half"
    description = ""
    params = {}
    frequency = "daily"

    def screen(self, ctx, symbols):
        mid = max(1, len(symbols) // 2)
        return symbols[mid:]


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
        assert len(result["screened_symbols"]) == 2

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

    def test_mixed_freq_daily_then_monthly_match_dates_are_daily(self):
        class DailyScreener(ScreenerStrategy):
            name = "daily-pass"
            description = ""
            params = {}
            frequency = "daily"
            def screen(self, ctx, symbols):
                return symbols

        class MonthlyScreener(ScreenerStrategy):
            name = "monthly-pass"
            description = ""
            params = {}
            frequency = "monthly"
            def screen(self, ctx, symbols):
                return symbols

        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[DailyScreener(), MonthlyScreener()],
            trader=None,
        )
        result = engine.run()
        assert "screened_symbols" in result
        items = result["screened_symbols"]
        assert len(items) > 0
        for item in items:
            for d in item["match_dates"]:
                assert detect_frequency(d) == "daily"

    def test_mixed_freq_monthly_then_daily_match_dates_are_daily(self):
        class DailyScreener(ScreenerStrategy):
            name = "daily-pass"
            description = ""
            params = {}
            frequency = "daily"
            def screen(self, ctx, symbols):
                return symbols

        class MonthlyScreener(ScreenerStrategy):
            name = "monthly-pass"
            description = ""
            params = {}
            frequency = "monthly"
            def screen(self, ctx, symbols):
                return symbols

        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[MonthlyScreener(), DailyScreener()],
            trader=None,
        )
        result = engine.run()
        assert "screened_symbols" in result
        items = result["screened_symbols"]
        assert len(items) > 0
        all_dates = set(data[list(data.keys())[0]]["date"].tolist())
        for item in items:
            assert len(item["match_dates"]) > 0
            for d in item["match_dates"]:
                assert detect_frequency(d) == "daily"
                assert d in all_dates, f"{d} is not a daily trading date"


class TestJoinModesScreenerBacktest:
    def _make_data(self):
        return {
            "AAA.SH": _make_stock_df(100, seed=42, base_price=50.0),
            "BBB.SZ": _make_stock_df(100, seed=43, base_price=100.0),
        }

    def test_independent_union(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[OddMonthScreener(), EvenMonthScreener()],
            join_modes=["independent"],
        )
        result = engine.run()
        items = result["screened_symbols"]
        assert len(items) == 2
        all_months = set()
        for item in items:
            for d in item["match_dates"]:
                all_months.add(d)
        assert len(all_months) > 1

    def test_correlated_no_overlap(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[OddMonthScreener(), EvenMonthScreener()],
            join_modes=["correlated"],
        )
        result = engine.run()
        items = result["screened_symbols"]
        assert len(items) == 0

    def test_default_is_independent(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[OddMonthScreener(), EvenMonthScreener()],
        )
        result = engine.run()
        items = result["screened_symbols"]
        assert len(items) == 2

    def test_frequency_format(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[OddMonthScreener()],
        )
        result = engine.run()
        items = result["screened_symbols"]
        assert len(items) > 0
        for item in items:
            for d in item["match_dates"]:
                assert detect_frequency(d) == "monthly"

    def test_mixed_freq_finest_output(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), OddMonthScreener()],
            join_modes=["independent"],
        )
        result = engine.run()
        items = result["screened_symbols"]
        assert len(items) > 0
        for item in items:
            for d in item["match_dates"]:
                assert detect_frequency(d) == "daily"


class TestJoinModesScreenerOnly:
    def _make_data(self):
        return {
            "AAA.SH": _make_stock_df(100, seed=42, base_price=50.0),
            "BBB.SZ": _make_stock_df(100, seed=43, base_price=100.0),
        }

    def test_independent_union(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            join_modes=["independent"],
        )
        result = engine.run(mode="screen")
        assert len(result["screened_symbols"]) == 2

    def test_correlated_intersection(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            join_modes=["correlated"],
        )
        result = engine.run(mode="screen")
        assert len(result["screened_symbols"]) == 0

    def test_correlated_overlap(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), TopOneScreener()],
            join_modes=["correlated"],
        )
        result = engine.run(mode="screen")
        assert len(result["screened_symbols"]) == 1

    def test_default_is_independent(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
        )
        result = engine.run(mode="screen")
        assert len(result["screened_symbols"]) == 2


class TestJoinModesFullBacktest:
    def _make_data(self):
        return {
            "AAA.SH": _make_stock_df(100, seed=42, base_price=50.0),
            "BBB.SZ": _make_stock_df(100, seed=43, base_price=100.0),
        }

    def test_independent_has_trades(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=BuyAndHoldTrader(),
            join_modes=["independent"],
        )
        result = engine.run()
        assert len(result["trades"]) > 0

    def test_correlated_no_overlap_no_trades(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=BuyAndHoldTrader(),
            join_modes=["correlated"],
        )
        result = engine.run()
        assert len(result["trades"]) == 0

    def test_default_is_independent(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        assert len(result["trades"]) > 0
