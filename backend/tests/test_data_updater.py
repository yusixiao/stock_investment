import json
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

from services.data_updater import (
    _fetch_hist_with_retry,
    _hist_df_to_records,
    _load_tracker,
    _save_tracker,
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
        assert records[1]["date"] == "2026-04-11"


class TestTracker:
    def test_load_empty(self, tmp_path):
        path = tmp_path / "tracker.json"
        assert _load_tracker(path) == {}

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "tracker.json"
        data = {"000001.SZ": "2026-04-11", "600028.SH": "2026-04-10"}
        _save_tracker(data, path)
        loaded = _load_tracker(path)
        assert loaded == data


class TestRunIncrementalUpdate:
    @patch("services.data_updater.date")
    @patch("services.data_updater.invalidate_cache")
    @patch("services.data_updater._save_log")
    @patch("services.data_updater._fetch_hist_with_retry")
    def test_uses_tracker_for_start_date(self, mock_fetch, mock_save_log, mock_invalidate, mock_date, tmp_path):
        mock_date.today.return_value = date(2026, 4, 13)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        existing_df = pd.DataFrame({
            "date": ["2026-04-10", "2026-04-09"],
            "open": [5.83, 5.89], "high": [5.84, 5.94],
            "low": [5.81, 5.82], "close": [5.81, 5.84],
            "volume": [1e8, 1.5e8], "amount": [7e8, 9e8],
        })
        filepath = tmp_path / "600028.SH.parquet"
        existing_df.to_parquet(filepath, index=False)

        tracker_path = tmp_path / "tracker.json"
        _save_tracker({"600028.SH": "2026-04-10"}, tracker_path)

        mock_fetch.return_value = _make_hist_df([
            ["2026-04-11", "600028", 5.90, 5.92, 5.95, 5.88, 2e8, 1.1e9, 1.0, 1.5, 0.08, 0.5],
            ["2026-04-13", "600028", 5.95, 5.97, 5.99, 5.93, 1.5e8, 9e8, 0.8, 0.8, 0.05, 0.4],
        ])

        result = run_incremental_update(data_dir=tmp_path, tracker_path=tracker_path)
        assert result.updated == 1

        mock_fetch.assert_called_once_with("600028", "20260411", "20260413", max_attempts=3)

        tracker = _load_tracker(tracker_path)
        assert tracker["600028.SH"] == "2026-04-13"

        updated_df = pd.read_parquet(filepath)
        assert len(updated_df) == 4

    @patch("services.data_updater.date")
    @patch("services.data_updater.invalidate_cache")
    @patch("services.data_updater._save_log")
    @patch("services.data_updater._fetch_hist_with_retry")
    def test_skips_when_tracker_is_today(self, mock_fetch, mock_save_log, mock_invalidate, mock_date, tmp_path):
        mock_date.today.return_value = date(2026, 4, 11)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        filepath = tmp_path / "600028.SH.parquet"
        pd.DataFrame({
            "date": ["2026-04-11"],
            "open": [5.83], "high": [5.84],
            "low": [5.81], "close": [5.81],
            "volume": [1e8], "amount": [7e8],
        }).to_parquet(filepath, index=False)

        tracker_path = tmp_path / "tracker.json"
        _save_tracker({"600028.SH": "2026-04-11"}, tracker_path)

        result = run_incremental_update(data_dir=tmp_path, tracker_path=tracker_path)
        assert result.skipped == 1
        assert result.updated == 0
        assert mock_fetch.call_count == 0

    @patch("services.data_updater.date")
    @patch("services.data_updater.invalidate_cache")
    @patch("services.data_updater._save_log")
    @patch("services.data_updater._fetch_hist_with_retry")
    def test_failed_stock_not_tracked(self, mock_fetch, mock_save_log, mock_invalidate, mock_date, tmp_path):
        mock_date.today.return_value = date(2026, 4, 13)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        filepath = tmp_path / "000064.SZ.parquet"
        pd.DataFrame({
            "date": ["2026-04-10"],
            "open": [5.0], "high": [5.1],
            "low": [4.9], "close": [5.0],
            "volume": [1e6], "amount": [5e6],
        }).to_parquet(filepath, index=False)

        tracker_path = tmp_path / "tracker.json"
        _save_tracker({"000064.SZ": "2026-04-10"}, tracker_path)

        mock_fetch.side_effect = RuntimeError("000064 3次重试失败: timeout")

        result = run_incremental_update(data_dir=tmp_path, tracker_path=tracker_path)
        assert result.failed == 1

        tracker = _load_tracker(tracker_path)
        assert tracker["000064.SZ"] == "2026-04-10"

    @patch("services.data_updater.date")
    @patch("services.data_updater.invalidate_cache")
    @patch("services.data_updater._save_log")
    @patch("services.data_updater._fetch_hist_with_retry")
    def test_no_tracker_entry_uses_2010(self, mock_fetch, mock_save_log, mock_invalidate, mock_date, tmp_path):
        mock_date.today.return_value = date(2026, 4, 13)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        filepath = tmp_path / "600028.SH.parquet"
        pd.DataFrame({
            "date": ["2026-04-10"],
            "open": [5.83], "high": [5.84],
            "low": [5.81], "close": [5.81],
            "volume": [1e8], "amount": [7e8],
        }).to_parquet(filepath, index=False)

        tracker_path = tmp_path / "tracker.json"
        _save_tracker({}, tracker_path)

        mock_fetch.return_value = pd.DataFrame()

        result = run_incremental_update(data_dir=tmp_path, tracker_path=tracker_path)

        mock_fetch.assert_called_once_with("600028", "20100104", "20260413", max_attempts=3)
