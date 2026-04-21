import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from services.dividend_updater import (
    EM_COLUMNS,
    SINA_TO_EM_MAP,
    fetch_dividend_em,
    fetch_dividend_sina,
    map_sina_to_em,
    fetch_symbol_dividend,
    run_dividend_update,
)


@pytest.fixture
def tmp_dividend_dir(tmp_path):
    return tmp_path


def _make_em_df():
    return pd.DataFrame({
        "报告期": ["2024-12-31", "2023-12-31"],
        "业绩披露日期": ["2025-03-15", "2024-03-15"],
        "送转股份-送转总比例": [0.0, 0.0],
        "送转股份-送股比例": [0.0, 0.0],
        "送转股份-转股比例": [0.0, 0.0],
        "现金分红-现金分红比例": [3.5, 2.8],
        "现金分红-现金分红比例描述": ["10派3.5元", "10派2.8元"],
        "现金分红-股息率": [0.02, 0.015],
        "每股收益": [1.5, 1.2],
        "每股净资产": [10.0, 9.5],
        "每股公积金": [3.0, 2.8],
        "每股未分配利润": [5.0, 4.5],
        "净利润同比增长": [0.1, 0.05],
        "总股本": [1000000.0, 1000000.0],
        "预案公告日": ["2025-03-20", "2024-03-20"],
        "股权登记日": ["2025-06-10", "2024-06-10"],
        "除权除息日": ["2025-06-11", "2024-06-11"],
        "方案进度": ["实施分配", "实施分配"],
        "最新公告日期": ["2025-03-20", "2024-03-20"],
    })


def _make_sina_df():
    return pd.DataFrame({
        "公告日期": ["2025-03-20", "2024-03-20"],
        "送股": [0.0, 0.0],
        "转增": [0.0, 0.0],
        "派息": [3.5, 2.8],
        "进度": ["实施", "实施"],
        "除权除息日": ["2025-06-11", "2024-06-11"],
        "股权登记日": ["2025-06-10", "2024-06-10"],
        "红股上市日": [None, None],
    })


class TestFetchDividendEm:
    @patch("services.dividend_updater.time.sleep")
    @patch("services.dividend_updater._call_em_api")
    def test_returns_dataframe(self, mock_api, mock_sleep):
        mock_api.return_value = _make_em_df()
        result = fetch_dividend_em("000001")
        assert result is not None
        assert len(result) == 2
        assert list(result.columns) == EM_COLUMNS
        mock_api.assert_called_once_with("000001")

    @patch("services.dividend_updater.time.sleep")
    @patch("services.dividend_updater._call_em_api")
    def test_api_failure_returns_none(self, mock_api, mock_sleep):
        mock_api.side_effect = Exception("timeout")
        result = fetch_dividend_em("000001")
        assert result is None


class TestFetchDividendSina:
    @patch("services.dividend_updater.time.sleep")
    @patch("services.dividend_updater._call_sina_api")
    def test_returns_dataframe(self, mock_api, mock_sleep):
        mock_api.return_value = _make_sina_df()
        result = fetch_dividend_sina("000001")
        assert result is not None
        assert len(result) == 2
        mock_api.assert_called_once_with("000001")

    @patch("services.dividend_updater.time.sleep")
    @patch("services.dividend_updater._call_sina_api")
    def test_api_failure_returns_none(self, mock_api, mock_sleep):
        mock_api.side_effect = Exception("timeout")
        result = fetch_dividend_sina("000001")
        assert result is None


class TestMapSinaToEm:
    def test_maps_columns_correctly(self):
        sina_df = _make_sina_df()
        result = map_sina_to_em(sina_df)
        assert list(result.columns) == EM_COLUMNS
        assert result.iloc[0]["现金分红-现金分红比例"] == 3.5
        assert result.iloc[0]["送转股份-送股比例"] == 0.0
        assert result.iloc[0]["送转股份-转股比例"] == 0.0
        assert result.iloc[0]["送转股份-送转总比例"] == 0.0
        assert result.iloc[0]["预案公告日"] == "2025-03-20"
        assert result.iloc[0]["方案进度"] == "实施"
        assert pd.isna(result.iloc[0]["每股收益"])

    def test_computes_total_ratio(self):
        sina_df = pd.DataFrame({
            "公告日期": ["2025-03-20"],
            "送股": [2.0],
            "转增": [3.0],
            "派息": [1.0],
            "进度": ["实施"],
            "除权除息日": ["2025-06-11"],
            "股权登记日": ["2025-06-10"],
            "红股上市日": [None],
        })
        result = map_sina_to_em(sina_df)
        assert result.iloc[0]["送转股份-送转总比例"] == 5.0
        assert result.iloc[0]["送转股份-送股比例"] == 2.0
        assert result.iloc[0]["送转股份-转股比例"] == 3.0


class TestFetchSymbolDividend:
    @patch("services.dividend_updater.time.sleep")
    @patch("services.dividend_updater.fetch_dividend_em")
    def test_em_success(self, mock_em, mock_sleep):
        mock_em.return_value = _make_em_df()
        result = fetch_symbol_dividend("000001.SZ")
        assert result is not None
        assert len(result) == 2
        mock_em.assert_called_once_with("000001")

    @patch("services.dividend_updater.time.sleep")
    @patch("services.dividend_updater.fetch_dividend_sina")
    @patch("services.dividend_updater.fetch_dividend_em")
    def test_em_fail_fallback_sina(self, mock_em, mock_sina, mock_sleep):
        mock_em.return_value = None
        mock_sina.return_value = _make_sina_df()
        result = fetch_symbol_dividend("000001.SZ")
        assert result is not None
        assert list(result.columns) == EM_COLUMNS

    @patch("services.dividend_updater.time.sleep")
    @patch("services.dividend_updater.fetch_dividend_sina")
    @patch("services.dividend_updater.fetch_dividend_em")
    def test_both_fail_returns_none(self, mock_em, mock_sina, mock_sleep):
        mock_em.return_value = None
        mock_sina.return_value = None
        result = fetch_symbol_dividend("000001.SZ")
        assert result is None


@patch("services.dividend_updater.time.sleep")
class TestRunDividendUpdate:
    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_full_mode_creates_parquet(self, mock_fetch, mock_sleep, tmp_dividend_dir):
        mock_fetch.return_value = _make_em_df()
        symbols = ["000001.SZ"]
        result = run_dividend_update(
            mode="full", symbols=symbols, dividend_dir=tmp_dividend_dir
        )
        assert result["success"] == 1
        assert result["failed"] == 0
        pf = tmp_dividend_dir / "000001.SZ.parquet"
        assert pf.exists()
        df = pd.read_parquet(pf)
        assert len(df) == 2

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_full_mode_skips_existing(self, mock_fetch, mock_sleep, tmp_dividend_dir):
        existing = _make_em_df()
        pf = tmp_dividend_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        result = run_dividend_update(
            mode="full", symbols=["000001.SZ"], dividend_dir=tmp_dividend_dir
        )
        assert result["skipped"] == 1
        mock_fetch.assert_not_called()

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_full_mode_force_overwrites(self, mock_fetch, mock_sleep, tmp_dividend_dir):
        existing = _make_em_df().head(1)
        pf = tmp_dividend_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        mock_fetch.return_value = _make_em_df()
        result = run_dividend_update(
            mode="full", symbols=["000001.SZ"], dividend_dir=tmp_dividend_dir, force=True
        )
        assert result["success"] == 1
        df = pd.read_parquet(pf)
        assert len(df) == 2

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_incremental_merges_new(self, mock_fetch, mock_sleep, tmp_dividend_dir):
        existing = _make_em_df().tail(1)
        pf = tmp_dividend_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        mock_fetch.return_value = _make_em_df()
        result = run_dividend_update(
            mode="incremental", symbols=["000001.SZ"], dividend_dir=tmp_dividend_dir
        )
        assert result["success"] == 1
        df = pd.read_parquet(pf)
        assert len(df) == 2

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_incremental_skips_no_existing(self, mock_fetch, mock_sleep, tmp_dividend_dir):
        result = run_dividend_update(
            mode="incremental", symbols=["000001.SZ"], dividend_dir=tmp_dividend_dir
        )
        assert result["skipped"] == 1
        mock_fetch.assert_not_called()

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_progress_callback(self, mock_fetch, mock_sleep, tmp_dividend_dir):
        mock_fetch.return_value = _make_em_df()
        progress_calls = []
        def on_progress(current, total, phase):
            progress_calls.append((current, total, phase))
        run_dividend_update(
            mode="full", symbols=["000001.SZ", "000002.SZ"],
            dividend_dir=tmp_dividend_dir, on_progress=on_progress
        )
        assert len(progress_calls) > 0
        assert progress_calls[-1][0] == 2
        assert progress_calls[-1][1] == 2
