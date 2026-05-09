import json
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

from services.data_updater import (
    _fetch_hist_with_retry,
    _hist_df_to_records,
    run_incremental_update,
    UpdateResult,
)


def _make_hist_df(rows):
    return pd.DataFrame(rows, columns=["日期", "股票代码", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"])


class TestFetchHistWithRetry:
    @patch("services.data_updater.ak.stock_zh_a_hist")
    def test_success_on_first_try(self, mock_api):
        mock_api.return_value = pd.DataFrame({"日期": ["2026-04-11"]})
        result = _fetch_hist_with_retry("000001", "20260411", "20260411", max_attempts=3)
        assert len(result) == 1
        assert mock_api.call_count == 1

    @patch("services.data_updater.time.sleep")
    @patch("services.data_updater.ak.stock_zh_a_hist")
    def test_success_after_retry(self, mock_api, mock_sleep):
        mock_api.side_effect = [Exception("timeout"), pd.DataFrame({"日期": ["2026-04-11"]})]
        result = _fetch_hist_with_retry("000001", "20260411", "20260411", max_attempts=3)
        assert len(result) == 1
        assert mock_api.call_count == 2

    @patch("services.data_updater.time.sleep")
    @patch("services.data_updater.ak.stock_zh_a_hist")
    def test_all_retries_exhausted(self, mock_api, mock_sleep):
        mock_api.side_effect = Exception("timeout")
        with pytest.raises(RuntimeError, match="3次重试失败"):
            _fetch_hist_with_retry("000001", "20260411", "20260411", max_attempts=3)
        assert mock_api.call_count == 3


class TestHistDfToRecords:
    def test_converts_correctly(self):
        df = _make_hist_df([
            ["2026-04-10", "000001", 11.10, 11.09, 11.12, 11.06, 100000, 1100000, 0.54, -0.09, -0.01, 0.25],
            ["2026-04-11", "000001", 11.05, 11.07, 11.10, 11.03, 90000, 990000, 0.54, -0.18, -0.02, 0.21],
        ])
        records = _hist_df_to_records(df)
        assert len(records) == 2
        assert records[0]["date"] == "2026-04-10"
        assert records[0]["open"] == 11.10
        assert records[0]["close"] == 11.09
        assert records[0]["high"] == 11.12
        assert records[0]["low"] == 11.06
        assert records[1]["date"] == "2026-04-11"


class TestRunIncrementalUpdate:
    def test_requires_start_date(self, tmp_path):
        with pytest.raises(ValueError, match="start_date is required"):
            run_incremental_update(data_dir=tmp_path, start_date=None)

    @patch("services.data_updater.invalidate_cache")
    @patch("services.data_updater._save_log")
    @patch("services.data_updater._fetch_hist_with_retry")
    def test_appends_new_data(self, mock_fetch, mock_save_log, mock_invalidate, tmp_path):
        existing_df = pd.DataFrame({
            "date": ["2026-04-10", "2026-04-09"],
            "open": [5.83, 5.89], "high": [5.84, 5.94],
            "low": [5.81, 5.82], "close": [5.81, 5.84],
            "volume": [1e8, 1.5e8], "amount": [7e8, 9e8],
        })
        filepath = tmp_path / "600028.SH.parquet"
        existing_df.to_parquet(filepath, index=False)

        mock_fetch.return_value = _make_hist_df([
            ["2026-04-11", "600028", 5.90, 5.92, 5.95, 5.88, 2e8, 1.1e9, 1.0, 1.5, 0.08, 0.5],
        ])

        result = run_incremental_update(data_dir=tmp_path, start_date="2026-04-11")
        assert result.updated == 1

        updated_df = pd.read_parquet(filepath)
        assert len(updated_df) == 3
        assert updated_df.iloc[0]["date"] == "2026-04-11"

    @patch("services.data_updater.date")
    @patch("services.data_updater.invalidate_cache")
    @patch("services.data_updater._save_log")
    @patch("services.data_updater._fetch_hist_with_retry")
    def test_skips_when_already_updated(self, mock_fetch, mock_save_log, mock_invalidate, mock_date, tmp_path):
        mock_date.today.return_value = date(2026, 4, 11)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        existing_df = pd.DataFrame({
            "date": ["2026-04-11", "2026-04-10"],
            "open": [5.83, 5.89], "high": [5.84, 5.94],
            "low": [5.81, 5.82], "close": [5.81, 5.84],
            "volume": [1e8, 1.5e8], "amount": [7e8, 9e8],
        })
        filepath = tmp_path / "600028.SH.parquet"
        existing_df.to_parquet(filepath, index=False)

        result = run_incremental_update(data_dir=tmp_path, start_date="2026-04-11")
        assert result.updated == 0
        assert result.skipped == 1
        assert mock_fetch.call_count == 0

    @patch("services.data_updater.invalidate_cache")
    @patch("services.data_updater._save_log")
    @patch("services.data_updater._fetch_hist_with_retry")
    def test_creates_new_stock_file_from_empty_dir(self, mock_fetch, mock_save_log, mock_invalidate, tmp_path):
        mock_fetch.return_value = _make_hist_df([
            ["2026-04-11", "688001", 10.0, 10.2, 10.5, 9.8, 5e6, 5e7, 2.0, 1.0, 0.1, 0.5],
        ])

        with patch("services.data_updater.ak.stock_zh_a_spot_em") as mock_spot:
            mock_spot.return_value = pd.DataFrame({"代码": ["688001"]})
            result = run_incremental_update(data_dir=tmp_path, start_date="2026-04-11")

        assert result.new_stocks == 1
        new_file = tmp_path / "688001.SH.parquet"
        assert new_file.exists()

    @patch("services.data_updater.invalidate_cache")
    @patch("services.data_updater._save_log")
    @patch("services.data_updater._fetch_hist_with_retry")
    def test_deduplicates_existing_dates(self, mock_fetch, mock_save_log, mock_invalidate, tmp_path):
        existing_df = pd.DataFrame({
            "date": ["2026-04-10", "2026-04-09"],
            "open": [5.83, 5.89], "high": [5.84, 5.94],
            "low": [5.81, 5.82], "close": [5.81, 5.84],
            "volume": [1e8, 1.5e8], "amount": [7e8, 9e8],
        })
        filepath = tmp_path / "600028.SH.parquet"
        existing_df.to_parquet(filepath, index=False)

        mock_fetch.return_value = _make_hist_df([
            ["2026-04-10", "600028", 5.83, 5.81, 5.84, 5.81, 1e8, 7e8, 0.5, -0.1, -0.01, 0.25],
            ["2026-04-11", "600028", 5.90, 5.92, 5.95, 5.88, 2e8, 1.1e9, 1.0, 1.5, 0.08, 0.5],
        ])

        result = run_incremental_update(data_dir=tmp_path, start_date="2026-04-10")
        assert result.updated == 1

        updated_df = pd.read_parquet(filepath)
        assert len(updated_df) == 3
        dates = updated_df["date"].tolist()
        assert dates.count("2026-04-10") == 1
