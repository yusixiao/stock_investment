import pandas as pd
import numpy as np
import pytest

from services.market_data.indicator import calc_ma, calc_macd, calc_kdj, calc_boll


def _make_df(n=100):
    np.random.seed(42)
    close = 10 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n).strftime("%Y-%m-%d").tolist()[::-1],
        "open": close + np.random.randn(n) * 0.1,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(1e6, 1e7, n).astype(float),
        "amount": np.random.randint(1e7, 1e8, n).astype(float),
    })


class TestCalcMA:
    def test_returns_correct_columns(self):
        df = _make_df()
        result = calc_ma(df, windows=[5, 10, 20])
        assert "ma5" in result.columns
        assert "ma10" in result.columns
        assert "ma20" in result.columns

    def test_ma5_value(self):
        df = _make_df()
        result = calc_ma(df, windows=[5])
        sorted_df = df.sort_values("date").reset_index(drop=True)
        expected = sorted_df["close"].rolling(5).mean().iloc[-1]
        result_sorted = result.sort_values("date").reset_index(drop=True)
        assert abs(result_sorted["ma5"].iloc[-1] - expected) < 1e-6


class TestCalcMACD:
    def test_returns_dif_dea_macd(self):
        df = _make_df()
        result = calc_macd(df)
        assert "dif" in result.columns
        assert "dea" in result.columns
        assert "macd" in result.columns

    def test_macd_is_2x_diff(self):
        df = _make_df()
        result = calc_macd(df)
        result_sorted = result.sort_values("date").reset_index(drop=True)
        valid = result_sorted.dropna(subset=["dif", "dea", "macd"])
        diff = (valid["dif"] - valid["dea"]) * 2
        pd.testing.assert_series_equal(
            valid["macd"].reset_index(drop=True),
            diff.reset_index(drop=True),
            check_names=False,
            atol=1e-6,
        )


class TestCalcKDJ:
    def test_returns_k_d_j(self):
        df = _make_df()
        result = calc_kdj(df)
        assert "k" in result.columns
        assert "d" in result.columns
        assert "j" in result.columns


class TestCalcBOLL:
    def test_returns_upper_mid_lower(self):
        df = _make_df()
        result = calc_boll(df)
        assert "boll_upper" in result.columns
        assert "boll_mid" in result.columns
        assert "boll_lower" in result.columns

    def test_mid_equals_ma20(self):
        df = _make_df()
        result = calc_boll(df, window=20)
        ma_result = calc_ma(df, windows=[20])
        result_s = result.sort_values("date").reset_index(drop=True)
        ma_s = ma_result.sort_values("date").reset_index(drop=True)
        pd.testing.assert_series_equal(
            result_s["boll_mid"], ma_s["ma20"],
            check_names=False, atol=1e-6,
        )
