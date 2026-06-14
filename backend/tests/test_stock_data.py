"""services/stock_data.py 测试 — manual update 下线后只剩 aggregate_kline。"""

import pandas as pd

from services.market_data.stock_data import aggregate_kline


class TestAggregateKline:
    def _make_daily_df(self):
        dates = (
            pd.date_range("2026-03-02", "2026-04-10", freq="B")
            .strftime("%Y-%m-%d")
            .tolist()
        )
        n = len(dates)
        df = pd.DataFrame(
            {
                "date": dates[::-1],
                "open": [10.0 + i * 0.1 for i in range(n)][::-1],
                "high": [11.0 + i * 0.1 for i in range(n)][::-1],
                "low": [9.0 + i * 0.1 for i in range(n)][::-1],
                "close": [10.5 + i * 0.1 for i in range(n)][::-1],
                "volume": [1e6] * n,
                "amount": [1e7] * n,
            }
        )
        return df

    def test_weekly_reduces_rows(self):
        df = self._make_daily_df()
        result = aggregate_kline(df, period="weekly")
        assert len(result) < len(df)
        assert result.iloc[0]["date"] > result.iloc[-1]["date"]

    def test_weekly_ohlcv_correct(self):
        df = pd.DataFrame(
            {
                "date": ["2026-04-10", "2026-04-09", "2026-04-08", "2026-04-07"],
                "open": [10.0, 9.5, 9.0, 8.5],
                "high": [10.5, 10.0, 9.5, 9.0],
                "low": [9.8, 9.2, 8.8, 8.3],
                "close": [10.2, 9.8, 9.3, 8.8],
                "volume": [1e6, 2e6, 3e6, 4e6],
                "amount": [1e7, 2e7, 3e7, 4e7],
            }
        )
        result = aggregate_kline(df, period="weekly")
        row = result.iloc[0]
        assert row["open"] == 8.5
        assert row["high"] == 10.5
        assert row["low"] == 8.3
        assert row["close"] == 10.2
        assert row["volume"] == 10e6
        assert row["amount"] == 10e7

    def test_monthly_reduces_rows(self):
        df = self._make_daily_df()
        result = aggregate_kline(df, period="monthly")
        assert len(result) <= 2

    def test_preserves_descending_order(self):
        df = self._make_daily_df()
        result = aggregate_kline(df, period="weekly")
        assert result.iloc[0]["date"] > result.iloc[-1]["date"]
