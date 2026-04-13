import pandas as pd
import pytest
from pathlib import Path

from services.stock_data import (
    list_stocks,
    get_kline,
    get_latest_date,
    symbol_to_filepath,
)
from config import RAW_KLINE_DIR


class TestSymbolToFilepath:
    def test_sh_stock(self):
        result = symbol_to_filepath("600028")
        assert result == RAW_KLINE_DIR / "600028.SH.parquet"

    def test_sz_stock_0(self):
        result = symbol_to_filepath("000001")
        assert result == RAW_KLINE_DIR / "000001.SZ.parquet"

    def test_sz_stock_3(self):
        result = symbol_to_filepath("300163")
        assert result == RAW_KLINE_DIR / "300163.SZ.parquet"


class TestGetLatestDate:
    def test_returns_latest_date(self, tmp_path):
        df = pd.DataFrame({
            "date": ["2026-04-10", "2026-04-09", "2026-04-08"],
            "open": [5.83, 5.89, 5.80],
            "high": [5.84, 5.94, 5.90],
            "low": [5.81, 5.82, 5.76],
            "close": [5.81, 5.84, 5.89],
            "volume": [1e8, 1.5e8, 2e8],
            "amount": [7e8, 9e8, 1.3e9],
        })
        path = tmp_path / "test.parquet"
        df.to_parquet(path, index=False)
        assert get_latest_date(path) == "2026-04-10"


class TestGetKline:
    def test_returns_dataframe_with_date_range(self, tmp_path):
        dates = [f"2026-04-{10-i:02d}" for i in range(5)]
        df = pd.DataFrame({
            "date": dates,
            "open": [1.0]*5, "high": [2.0]*5, "low": [0.5]*5,
            "close": [1.5]*5, "volume": [1e6]*5, "amount": [1e7]*5,
        })
        path = tmp_path / "test.parquet"
        df.to_parquet(path, index=False)
        result = get_kline(path, start_date="2026-04-07", end_date="2026-04-09")
        assert len(result) == 3
        assert result.iloc[0]["date"] == "2026-04-09"

    def test_returns_all_if_no_range(self, tmp_path):
        df = pd.DataFrame({
            "date": ["2026-04-10", "2026-04-09"],
            "open": [1.0]*2, "high": [2.0]*2, "low": [0.5]*2,
            "close": [1.5]*2, "volume": [1e6]*2, "amount": [1e7]*2,
        })
        path = tmp_path / "test.parquet"
        df.to_parquet(path, index=False)
        result = get_kline(path)
        assert len(result) == 2


class TestListStocks:
    def test_lists_parquet_files(self, tmp_path):
        for name in ["600028.SH.parquet", "000001.SZ.parquet"]:
            df = pd.DataFrame({
                "date": ["2026-04-10"], "open": [1.0], "high": [2.0],
                "low": [0.5], "close": [1.5], "volume": [1e6], "amount": [1e7],
            })
            df.to_parquet(tmp_path / name, index=False)
        result = list_stocks(tmp_path)
        assert len(result) == 2
        symbols = [s["symbol"] for s in result]
        assert "600028.SH" in symbols
        assert "000001.SZ" in symbols

    def test_search_filter(self, tmp_path):
        for name in ["600028.SH.parquet", "000001.SZ.parquet"]:
            df = pd.DataFrame({
                "date": ["2026-04-10"], "open": [1.0], "high": [2.0],
                "low": [0.5], "close": [1.5], "volume": [1e6], "amount": [1e7],
            })
            df.to_parquet(tmp_path / name, index=False)
        result = list_stocks(tmp_path, search="600028")
        assert len(result) == 1
