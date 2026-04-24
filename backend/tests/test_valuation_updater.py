import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from services.valuation_updater import (
    INDICATOR_MAP,
    fetch_single_indicator,
    fetch_symbol_valuation,
    run_valuation_update,
)


@pytest.fixture
def tmp_valuation_dir(tmp_path):
    return tmp_path


def _mock_baidu_response(dates, values):
    return pd.DataFrame({"date": dates, "value": values})


class TestFetchSingleIndicator:
    @patch("services.valuation_updater.ak.stock_zh_valuation_baidu")
    def test_returns_renamed_series(self, mock_api):
        mock_api.return_value = _mock_baidu_response(
            ["2024-01-01", "2024-01-18"], [10.5, 11.2]
        )
        result = fetch_single_indicator("000001", "市盈率(TTM)", "pe_ttm", "全部")
        assert list(result.columns) == ["date", "pe_ttm"]
        assert len(result) == 2
        mock_api.assert_called_once_with(symbol="000001", indicator="市盈率(TTM)", period="全部")

    @patch("services.valuation_updater.ak.stock_zh_valuation_baidu")
    def test_api_failure_returns_none(self, mock_api):
        mock_api.side_effect = Exception("timeout")
        result = fetch_single_indicator("000001", "市盈率(TTM)", "pe_ttm", "全部")
        assert result is None


class TestFetchSymbolValuation:
    @patch("services.valuation_updater.fetch_single_indicator")
    def test_merges_all_indicators(self, mock_fetch):
        dates = ["2024-01-01", "2024-01-18"]
        def side_effect(symbol, indicator, col_name, period):
            return pd.DataFrame({"date": dates, col_name: [1.0, 2.0]})
        mock_fetch.side_effect = side_effect
        result = fetch_symbol_valuation("000001.SZ", "全部")
        assert result is not None
        assert set(result.columns) == {"date", "total_mv", "pe_ttm", "pe_static", "pb", "pcf"}
        assert len(result) == 2

    @patch("services.valuation_updater.fetch_single_indicator")
    def test_all_fail_returns_none(self, mock_fetch):
        mock_fetch.return_value = None
        result = fetch_symbol_valuation("000001.SZ", "全部")
        assert result is None

    @patch("services.valuation_updater.fetch_single_indicator")
    def test_partial_fail_still_merges(self, mock_fetch):
        dates = ["2024-01-01", "2024-01-18"]
        def side_effect(symbol, indicator, col_name, period):
            if col_name == "pcf":
                return None
            return pd.DataFrame({"date": dates, col_name: [1.0, 2.0]})
        mock_fetch.side_effect = side_effect
        result = fetch_symbol_valuation("000001.SZ", "全部")
        assert result is not None
        assert "pcf" not in result.columns
        assert "pe_ttm" in result.columns


class TestRunValuationUpdate:
    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_full_mode_creates_parquet(self, mock_fetch, tmp_valuation_dir):
        mock_fetch.return_value = pd.DataFrame({
            "date": ["2024-01-18", "2024-01-01"],
            "total_mv": [100.0, 90.0],
            "pe_ttm": [15.0, 14.0],
            "pe_static": [16.0, 15.0],
            "pb": [2.0, 1.9],
            "pcf": [8.0, 7.5],
        })
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="full", symbols=symbols, valuation_dir=tmp_valuation_dir
        )
        assert result["success"] == 1
        assert result["failed"] == 0
        pf = tmp_valuation_dir / "000001.SZ.parquet"
        assert pf.exists()
        df = pd.read_parquet(pf)
        assert df.iloc[0]["date"] == "2024-01-18"

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_full_mode_skips_existing(self, mock_fetch, tmp_valuation_dir):
        existing = pd.DataFrame({
            "date": ["2024-01-01"],
            "total_mv": [90.0], "pe_ttm": [14.0],
            "pe_static": [15.0], "pb": [1.9], "pcf": [7.5],
        })
        pf = tmp_valuation_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="full", symbols=symbols, valuation_dir=tmp_valuation_dir
        )
        assert result["skipped"] == 1
        mock_fetch.assert_not_called()

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_full_mode_force_overwrites(self, mock_fetch, tmp_valuation_dir):
        existing = pd.DataFrame({
            "date": ["2024-01-01"],
            "total_mv": [90.0], "pe_ttm": [14.0],
            "pe_static": [15.0], "pb": [1.9], "pcf": [7.5],
        })
        pf = tmp_valuation_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        mock_fetch.return_value = pd.DataFrame({
            "date": ["2024-01-18", "2024-01-01"],
            "total_mv": [100.0, 90.0],
            "pe_ttm": [15.0, 14.0],
            "pe_static": [16.0, 15.0],
            "pb": [2.0, 1.9],
            "pcf": [8.0, 7.5],
        })
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="full", symbols=symbols, valuation_dir=tmp_valuation_dir, force=True
        )
        assert result["success"] == 1
        df = pd.read_parquet(pf)
        assert len(df) == 2

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_incremental_appends_new_data(self, mock_fetch, tmp_valuation_dir):
        existing = pd.DataFrame({
            "date": ["2024-01-18", "2024-01-01"],
            "total_mv": [100.0, 90.0],
            "pe_ttm": [15.0, 14.0],
            "pe_static": [16.0, 15.0],
            "pb": [2.0, 1.9],
            "pcf": [8.0, 7.5],
        })
        pf = tmp_valuation_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        mock_fetch.return_value = pd.DataFrame({
            "date": ["2024-02-05", "2024-01-18", "2024-01-01"],
            "total_mv": [110.0, 100.0, 90.0],
            "pe_ttm": [16.0, 15.0, 14.0],
            "pe_static": [17.0, 16.0, 15.0],
            "pb": [2.1, 2.0, 1.9],
            "pcf": [8.5, 8.0, 7.5],
        })
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="incremental", symbols=symbols, valuation_dir=tmp_valuation_dir
        )
        assert result["success"] == 1
        df = pd.read_parquet(pf)
        assert len(df) == 3
        assert df.iloc[0]["date"] == "2024-02-05"

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_incremental_skips_no_existing(self, mock_fetch, tmp_valuation_dir):
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="incremental", symbols=symbols, valuation_dir=tmp_valuation_dir
        )
        assert result["skipped"] == 1
        mock_fetch.assert_not_called()

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_progress_callback(self, mock_fetch, tmp_valuation_dir):
        mock_fetch.return_value = pd.DataFrame({
            "date": ["2024-01-01"],
            "total_mv": [90.0], "pe_ttm": [14.0],
            "pe_static": [15.0], "pb": [1.9], "pcf": [7.5],
        })
        progress_calls = []
        def on_progress(current, total, phase):
            progress_calls.append((current, total, phase))
        symbols = ["000001.SZ", "000002.SZ"]
        run_valuation_update(
            mode="full", symbols=symbols, valuation_dir=tmp_valuation_dir,
            on_progress=on_progress
        )
        assert len(progress_calls) > 0
        assert progress_calls[-1][0] == 2
        assert progress_calls[-1][1] == 2
