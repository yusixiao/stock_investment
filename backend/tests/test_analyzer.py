import pytest
from services.backtest.analyzer import compute_metrics


class TestComputeMetrics:
    def _make_equity_curve(self, values):
        import pandas as pd
        dates = pd.date_range("2024-01-01", periods=len(values), freq="B").strftime("%Y-%m-%d").tolist()
        return [{"date": d, "total_value": v, "cash": v * 0.5, "market_value": v * 0.5} for d, v in zip(dates, values)]

    def test_basic_positive_return(self):
        curve = self._make_equity_curve([100_000, 105_000, 110_000, 115_000, 120_000])
        trades = [
            {"direction": "buy", "shares": 100, "price": 100, "amount": 10000},
            {"direction": "sell", "shares": 100, "price": 120, "amount": 12000},
        ]
        m = compute_metrics(curve, trades, initial_capital=100_000)
        assert m["total_return"] == pytest.approx(0.2, abs=0.01)
        assert m["trade_count"] == 2

    def test_max_drawdown(self):
        curve = self._make_equity_curve([100_000, 110_000, 90_000, 95_000])
        m = compute_metrics(curve, [], initial_capital=100_000)
        expected_dd = (110_000 - 90_000) / 110_000
        assert m["max_drawdown"] == pytest.approx(expected_dd, abs=0.01)

    def test_win_rate(self):
        trades = [
            {"direction": "sell", "shares": 100, "price": 120, "amount": 12000},
            {"direction": "sell", "shares": 100, "price": 80, "amount": 8000},
            {"direction": "buy", "shares": 100, "price": 100, "amount": 10000},
            {"direction": "buy", "shares": 100, "price": 100, "amount": 10000},
        ]
        curve = self._make_equity_curve([100_000, 100_000])
        m = compute_metrics(curve, trades, initial_capital=100_000)
        assert "win_rate" in m

    def test_no_trades(self):
        curve = self._make_equity_curve([100_000, 100_000, 100_000])
        m = compute_metrics(curve, [], initial_capital=100_000)
        assert m["total_return"] == 0.0
        assert m["trade_count"] == 0
        assert m["win_rate"] == 0.0

    def test_annualized_return(self):
        values = [100_000 + i * 100 for i in range(253)]
        curve = self._make_equity_curve(values)
        m = compute_metrics(curve, [], initial_capital=100_000)
        assert m["annualized_return"] > 0

    def test_sharpe_ratio(self):
        values = [100_000 + i * 50 for i in range(100)]
        curve = self._make_equity_curve(values)
        m = compute_metrics(curve, [], initial_capital=100_000)
        assert "sharpe_ratio" in m

    def test_single_day(self):
        curve = self._make_equity_curve([100_000])
        m = compute_metrics(curve, [], initial_capital=100_000)
        assert m["total_return"] == 0.0
        assert m["max_drawdown"] == 0.0
