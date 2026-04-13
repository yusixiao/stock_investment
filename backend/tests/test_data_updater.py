import json
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

from services.data_updater import (
    map_spot_to_record,
    retry_fetch_spot,
    run_incremental_update,
    UpdateResult,
)


class TestMapSpotToRecord:
    def test_maps_fields_correctly(self):
        row = pd.Series({
            "代码": "600028",
            "今开": 5.83,
            "最高": 5.84,
            "最低": 5.81,
            "最新价": 5.81,
            "成交量": 129726922,
            "成交额": 755147000,
        })
        result = map_spot_to_record(row, "2026-04-11")
        assert result["date"] == "2026-04-11"
        assert result["open"] == 5.83
        assert result["high"] == 5.84
        assert result["low"] == 5.81
        assert result["close"] == 5.81
        assert result["volume"] == 129726922
        assert result["amount"] == 755147000

    def test_exchange_mapping_sh(self):
        row = pd.Series({"代码": "600028", "今开": 1, "最高": 1, "最低": 1, "最新价": 1, "成交量": 1, "成交额": 1})
        result = map_spot_to_record(row, "2026-04-11")
        assert result["_exchange"] == "SH"

    def test_exchange_mapping_sz(self):
        row = pd.Series({"代码": "000001", "今开": 1, "最高": 1, "最低": 1, "最新价": 1, "成交量": 1, "成交额": 1})
        result = map_spot_to_record(row, "2026-04-11")
        assert result["_exchange"] == "SZ"


class TestRetryFetchSpot:
    @patch("services.data_updater.ak.stock_zh_a_spot_em")
    def test_success_on_first_try(self, mock_api):
        mock_api.return_value = pd.DataFrame({"代码": ["600028"]})
        result = retry_fetch_spot(max_attempts=3)
        assert len(result) == 1
        assert mock_api.call_count == 1

    @patch("services.data_updater.time.sleep")
    @patch("services.data_updater.ak.stock_zh_a_spot_em")
    def test_success_after_retry(self, mock_api, mock_sleep):
        mock_api.side_effect = [Exception("timeout"), pd.DataFrame({"代码": ["600028"]})]
        result = retry_fetch_spot(max_attempts=3)
        assert len(result) == 1
        assert mock_api.call_count == 2

    @patch("services.data_updater.time.sleep")
    @patch("services.data_updater.ak.stock_zh_a_spot_em")
    def test_all_retries_exhausted(self, mock_api, mock_sleep):
        mock_api.side_effect = Exception("timeout")
        with pytest.raises(RuntimeError, match="20 次重试后仍然失败"):
            retry_fetch_spot(max_attempts=20)
        assert mock_api.call_count == 20


class TestRunIncrementalUpdate:
    @patch("services.data_updater._save_log")
    @patch("services.data_updater.retry_fetch_spot")
    def test_appends_new_data(self, mock_fetch, mock_save_log, tmp_path):
        existing_df = pd.DataFrame({
            "date": ["2026-04-10", "2026-04-09"],
            "open": [5.83, 5.89], "high": [5.84, 5.94],
            "low": [5.81, 5.82], "close": [5.81, 5.84],
            "volume": [1e8, 1.5e8], "amount": [7e8, 9e8],
        })
        filepath = tmp_path / "600028.SH.parquet"
        existing_df.to_parquet(filepath, index=False)

        mock_fetch.return_value = pd.DataFrame({
            "代码": ["600028"],
            "今开": [5.90], "最高": [5.95], "最低": [5.88],
            "最新价": [5.92], "成交量": [2e8], "成交额": [1.1e9],
        })

        result = run_incremental_update(
            data_dir=tmp_path, today_str="2026-04-11"
        )
        assert result.updated == 1
        assert result.skipped == 0

        updated_df = pd.read_parquet(filepath)
        assert len(updated_df) == 3
        assert updated_df.iloc[0]["date"] == "2026-04-11"

    @patch("services.data_updater._save_log")
    @patch("services.data_updater.retry_fetch_spot")
    def test_skips_when_already_updated(self, mock_fetch, mock_save_log, tmp_path):
        existing_df = pd.DataFrame({
            "date": ["2026-04-11", "2026-04-10"],
            "open": [5.83, 5.89], "high": [5.84, 5.94],
            "low": [5.81, 5.82], "close": [5.81, 5.84],
            "volume": [1e8, 1.5e8], "amount": [7e8, 9e8],
        })
        filepath = tmp_path / "600028.SH.parquet"
        existing_df.to_parquet(filepath, index=False)

        mock_fetch.return_value = pd.DataFrame({
            "代码": ["600028"],
            "今开": [5.90], "最高": [5.95], "最低": [5.88],
            "最新价": [5.92], "成交量": [2e8], "成交额": [1.1e9],
        })

        result = run_incremental_update(
            data_dir=tmp_path, today_str="2026-04-11"
        )
        assert result.updated == 0
        assert result.skipped == 1

    @patch("services.data_updater._save_log")
    @patch("services.data_updater.retry_fetch_spot")
    def test_creates_new_stock_file(self, mock_fetch, mock_save_log, tmp_path):
        mock_fetch.return_value = pd.DataFrame({
            "代码": ["688001"],
            "今开": [10.0], "最高": [10.5], "最低": [9.8],
            "最新价": [10.2], "成交量": [5e6], "成交额": [5e7],
        })
        result = run_incremental_update(
            data_dir=tmp_path, today_str="2026-04-11"
        )
        assert result.new_stocks == 1
        new_file = tmp_path / "688001.SH.parquet"
        assert new_file.exists()
