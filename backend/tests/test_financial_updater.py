import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
from datetime import date
from unittest.mock import patch, MagicMock
from services.financial_updater import (
    generate_quarter_dates,
    fetch_quarter,
    split_and_save,
    get_existing_quarters,
    run_financial_update,
    _normalize_symbol,
    _quarter_to_date_str,
    COLUMNS,
)


def _make_yjbb_df(quarter="20241231", n=3):
    codes = ["000001", "600000", "300001"][:n]
    names = ["平安银行", "浦发银行", "特锐德"][:n]
    rows = []
    for i, (code, name) in enumerate(zip(codes, names)):
        rows.append({
            "序号": i + 1,
            "股票代码": code,
            "股票简称": name,
            "每股收益": 1.5 + i * 0.1,
            "营业总收入-营业总收入": 1e10 + i * 1e9,
            "营业总收入-同比增长": 5.0 + i,
            "营业总收入-季度环比增长": 2.0 + i,
            "净利润-净利润": 1e9 + i * 1e8,
            "净利润-同比增长": 10.0 + i,
            "净利润-季度环比增长": 3.0 + i,
            "每股净资产": 10.0 + i,
            "净资产收益率": 15.0 + i,
            "每股经营现金流量": 2.0 + i * 0.5,
            "销售毛利率": 30.0 + i,
            "所处行业": "银行" if i < 2 else "电气设备",
            "最新公告日期": "2025-04-20",
        })
    return pd.DataFrame(rows)


class TestGenerateQuarterDates:
    def test_default_generates_from_2000(self):
        quarters = generate_quarter_dates()
        assert quarters[0] == "20000331"
        assert "20001231" in quarters

    def test_custom_start_year(self):
        quarters = generate_quarter_dates(start_year=2020, end_date=date(2020, 12, 31))
        assert len(quarters) == 4
        assert quarters == ["20200331", "20200630", "20200930", "20201231"]

    def test_partial_year(self):
        quarters = generate_quarter_dates(start_year=2024, end_date=date(2024, 8, 15))
        assert quarters == ["20240331", "20240630"]

    def test_single_quarter(self):
        quarters = generate_quarter_dates(start_year=2024, end_date=date(2024, 3, 31))
        assert quarters == ["20240331"]


class TestNormalizeSymbol:
    def test_sh_codes(self):
        assert _normalize_symbol("600000") == "600000.SH"
        assert _normalize_symbol("900940") == "900940.SH"

    def test_sz_codes(self):
        assert _normalize_symbol("000001") == "000001.SZ"
        assert _normalize_symbol("300001") == "300001.SZ"
        assert _normalize_symbol("200000") == "200000.SZ"

    def test_bj_codes(self):
        assert _normalize_symbol("430047") == "430047.BJ"
        assert _normalize_symbol("830799") == "830799.BJ"


class TestQuarterToDateStr:
    def test_conversion(self):
        assert _quarter_to_date_str("20241231") == "2024-12-31"
        assert _quarter_to_date_str("20200331") == "2020-03-31"


class TestFetchQuarter:
    @patch("services.financial_updater.time.sleep")
    @patch("services.financial_updater._call_api")
    def test_success(self, mock_api, mock_sleep):
        mock_api.return_value = _make_yjbb_df()
        result = fetch_quarter("20241231")
        assert result is not None
        assert len(result) == 3
        mock_api.assert_called_once_with("20241231")

    @patch("services.financial_updater.time.sleep")
    @patch("services.financial_updater._call_api")
    def test_returns_none_on_failure(self, mock_api, mock_sleep):
        mock_api.side_effect = Exception("network error")
        result = fetch_quarter("20241231")
        assert result is None

    @patch("services.financial_updater.time.sleep")
    @patch("services.financial_updater._call_api")
    def test_returns_none_on_empty(self, mock_api, mock_sleep):
        mock_api.return_value = pd.DataFrame()
        result = fetch_quarter("20241231")
        assert result is None

    @patch("services.financial_updater.time.sleep")
    @patch("services.financial_updater._call_api")
    def test_retries_on_failure(self, mock_api, mock_sleep):
        mock_api.side_effect = [Exception("fail"), _make_yjbb_df()]
        result = fetch_quarter("20241231")
        assert result is not None
        assert mock_api.call_count == 2


class TestSplitAndSave:
    def test_creates_parquet_files(self, tmp_path):
        df = _make_yjbb_df()
        result = split_and_save(df, "20241231", tmp_path)
        assert result["saved"] == 3
        assert (tmp_path / "000001.SZ.parquet").exists()
        assert (tmp_path / "600000.SH.parquet").exists()
        assert (tmp_path / "300001.SZ.parquet").exists()

    def test_parquet_has_correct_columns(self, tmp_path):
        df = _make_yjbb_df(n=1)
        split_and_save(df, "20241231", tmp_path)
        saved = pd.read_parquet(tmp_path / "000001.SZ.parquet")
        assert "报告期" in saved.columns
        assert saved.iloc[0]["报告期"] == "2024-12-31"
        assert "净资产收益率" in saved.columns
        assert "每股收益" in saved.columns

    def test_appends_to_existing(self, tmp_path):
        df1 = _make_yjbb_df(n=1)
        split_and_save(df1, "20240930", tmp_path)
        df2 = _make_yjbb_df(n=1)
        split_and_save(df2, "20241231", tmp_path)
        saved = pd.read_parquet(tmp_path / "000001.SZ.parquet")
        assert len(saved) == 2
        assert saved.iloc[0]["报告期"] == "2024-12-31"
        assert saved.iloc[1]["报告期"] == "2024-09-30"

    def test_overwrites_same_quarter(self, tmp_path):
        df1 = _make_yjbb_df(n=1)
        split_and_save(df1, "20241231", tmp_path)
        df2 = _make_yjbb_df(n=1)
        df2.at[0, "每股收益"] = 99.9
        split_and_save(df2, "20241231", tmp_path)
        saved = pd.read_parquet(tmp_path / "000001.SZ.parquet")
        assert len(saved) == 1
        assert saved.iloc[0]["每股收益"] == 99.9


class TestGetExistingQuarters:
    def test_reads_quarters_from_parquet(self, tmp_path):
        df = pd.DataFrame({"报告期": ["2024-12-31", "2024-09-30"]})
        df.to_parquet(tmp_path / "000001.SZ.parquet", index=False)
        quarters = get_existing_quarters(tmp_path)
        assert "20241231" in quarters
        assert "20240930" in quarters

    def test_empty_dir(self, tmp_path):
        quarters = get_existing_quarters(tmp_path)
        assert quarters == set()


@patch("services.financial_updater.time.sleep")
class TestRunFinancialUpdate:
    @patch("services.financial_updater.fetch_quarter")
    @patch("services.financial_updater.generate_quarter_dates")
    def test_full_mode(self, mock_quarters, mock_fetch, mock_sleep, tmp_path):
        mock_quarters.return_value = ["20241231"]
        mock_fetch.return_value = _make_yjbb_df()
        result = run_financial_update(mode="full", financial_dir=tmp_path)
        assert result["success"] == 1
        assert result["failed"] == 0
        assert result["total_saved"] == 3
        assert (tmp_path / "000001.SZ.parquet").exists()

    @patch("services.financial_updater.fetch_quarter")
    @patch("services.financial_updater.generate_quarter_dates")
    def test_full_mode_failure(self, mock_quarters, mock_fetch, mock_sleep, tmp_path):
        mock_quarters.return_value = ["20241231"]
        mock_fetch.return_value = None
        result = run_financial_update(mode="full", financial_dir=tmp_path)
        assert result["success"] == 0
        assert result["failed"] == 1
        assert result["errors"] == ["20241231"]

    @patch("services.financial_updater.fetch_quarter")
    @patch("services.financial_updater.generate_quarter_dates")
    def test_progress_callback(self, mock_quarters, mock_fetch, mock_sleep, tmp_path):
        mock_quarters.return_value = ["20240930", "20241231"]
        mock_fetch.return_value = _make_yjbb_df()
        calls = []
        def on_progress(current, total, phase):
            calls.append((current, total, phase))
        run_financial_update(mode="full", financial_dir=tmp_path, on_progress=on_progress)
        assert len(calls) == 2
        assert calls[-1][0] == 2
        assert calls[-1][1] == 2

    @patch("services.financial_updater.get_existing_quarters")
    @patch("services.financial_updater.fetch_quarter")
    @patch("services.financial_updater.generate_quarter_dates")
    def test_incremental_mode_fetches_recent(self, mock_quarters, mock_fetch, mock_existing, mock_sleep, tmp_path):
        mock_quarters.return_value = ["20240331", "20240630", "20240930", "20241231"]
        mock_existing.return_value = {"20240331", "20240630"}
        mock_fetch.return_value = _make_yjbb_df()
        result = run_financial_update(mode="incremental", financial_dir=tmp_path)
        assert result["success"] == 2
        assert mock_fetch.call_count == 2

    @patch("services.financial_updater.fetch_quarter")
    @patch("services.financial_updater.generate_quarter_dates")
    def test_multiple_quarters(self, mock_quarters, mock_fetch, mock_sleep, tmp_path):
        mock_quarters.return_value = ["20240930", "20241231"]
        mock_fetch.side_effect = [_make_yjbb_df(n=1), _make_yjbb_df(n=1)]
        result = run_financial_update(mode="full", financial_dir=tmp_path)
        assert result["success"] == 2
        saved = pd.read_parquet(tmp_path / "000001.SZ.parquet")
        assert len(saved) == 2
