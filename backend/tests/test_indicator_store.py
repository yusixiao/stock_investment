import math
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch

from services.indicator_store import compute_and_save, load_indicators, _indicator_path


def _make_df(n=100, seed=42):
    np.random.seed(seed)
    close = 10 + np.cumsum(np.random.randn(n) * 0.5)
    dates = (
        pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    )
    return pd.DataFrame(
        {
            "date": dates,
            "open": close + np.random.randn(n) * 0.1,
            "high": close + np.abs(np.random.randn(n) * 0.3),
            "low": close - np.abs(np.random.randn(n) * 0.3),
            "close": close,
            "volume": np.random.randint(1_000_000, 10_000_000, n).astype(float),
            "amount": np.random.randint(10_000_000, 100_000_000, n).astype(float),
        }
    )


class TestComputeAndSave:
    def test_creates_daily_indicator_file(self, tmp_path):
        with patch("services.indicator_store.INDICATOR_DIR", tmp_path):
            df = _make_df()
            compute_and_save("000001.SZ", df)
            assert (tmp_path / "daily" / "000001.SZ.parquet").exists()

    def test_creates_weekly_indicator_file(self, tmp_path):
        with patch("services.indicator_store.INDICATOR_DIR", tmp_path):
            df = _make_df()
            compute_and_save("000001.SZ", df)
            assert (tmp_path / "weekly" / "000001.SZ.parquet").exists()

    def test_creates_monthly_indicator_file(self, tmp_path):
        with patch("services.indicator_store.INDICATOR_DIR", tmp_path):
            df = _make_df()
            compute_and_save("000001.SZ", df)
            assert (tmp_path / "monthly" / "000001.SZ.parquet").exists()

    def test_daily_indicator_has_expected_columns(self, tmp_path):
        with patch("services.indicator_store.INDICATOR_DIR", tmp_path):
            df = _make_df()
            compute_and_save("000001.SZ", df)
            ind = pd.read_parquet(tmp_path / "daily" / "000001.SZ.parquet")
            for col in [
                "date",
                "ma5",
                "ma10",
                "ma20",
                "ma60",
                "dif",
                "dea",
                "macd",
                "k",
                "d",
                "j",
                "boll_mid",
                "boll_upper",
                "boll_lower",
            ]:
                assert col in ind.columns, f"missing column: {col}"

    def test_daily_indicator_row_count_matches_kline(self, tmp_path):
        with patch("services.indicator_store.INDICATOR_DIR", tmp_path):
            df = _make_df(100)
            compute_and_save("000001.SZ", df)
            ind = pd.read_parquet(tmp_path / "daily" / "000001.SZ.parquet")
            assert len(ind) == 100

    def test_ma5_values_are_numeric(self, tmp_path):
        with patch("services.indicator_store.INDICATOR_DIR", tmp_path):
            df = _make_df()
            compute_and_save("000001.SZ", df)
            ind = pd.read_parquet(tmp_path / "daily" / "000001.SZ.parquet")
            non_nan = ind["ma5"].dropna()
            assert len(non_nan) > 0
            assert all(isinstance(v, float) for v in non_nan)


class TestLoadIndicators:
    def test_returns_none_when_file_missing(self, tmp_path):
        with patch("services.indicator_store.INDICATOR_DIR", tmp_path):
            result = load_indicators("MISSING.SZ", "daily")
            assert result is None

    def test_returns_dataframe_when_file_exists(self, tmp_path):
        with patch("services.indicator_store.INDICATOR_DIR", tmp_path):
            df = _make_df()
            compute_and_save("000001.SZ", df)
            result = load_indicators("000001.SZ", "daily")
            assert result is not None
            assert isinstance(result, pd.DataFrame)
            assert "ma5" in result.columns
