import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import numpy as np
import pytest
from backend.services.qfq_cache import (
    compute_qfq, _get_implemented_dividends,
    get_qfq_kline, invalidate_cache, invalidate_all, get_latest_ex_date,
    _load_meta, _save_meta,
)


def _make_raw_df(rows):
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
    return df


def _make_dividend_df(rows):
    cols = ["除权除息日", "现金分红-现金分红比例", "送转股份-送股比例", "送转股份-转股比例", "方案进度"]
    return pd.DataFrame(rows, columns=cols)


class TestGetImplementedDividends:
    def test_empty(self):
        result = _get_implemented_dividends(pd.DataFrame())
        assert result.empty

    def test_none(self):
        result = _get_implemented_dividends(None)
        assert result.empty

    def test_filters_non_implemented(self):
        df = _make_dividend_df([
            ["2024-06-01", 5.0, 0, 0, "实施"],
            ["2024-07-01", 3.0, 0, 0, "预案"],
            ["2024-08-01", 2.0, 0, 0, "股东大会通过"],
        ])
        result = _get_implemented_dividends(df)
        assert len(result) == 1
        assert result.iloc[0]["现金分红-现金分红比例"] == 5.0

    def test_filters_invalid_dates(self):
        df = _make_dividend_df([
            ["2024-06-01", 5.0, 0, 0, "实施"],
            [None, 3.0, 0, 0, "实施"],
            ["invalid", 2.0, 0, 0, "实施"],
        ])
        result = _get_implemented_dividends(df)
        assert len(result) == 1


class TestComputeQfqNoDividend:
    def test_no_dividend_returns_same(self):
        raw = _make_raw_df([
            ["2024-01-03", 10.0, 11.0, 9.0, 10.5, 1000, 10000],
            ["2024-01-02", 9.5, 10.5, 9.0, 10.0, 900, 9000],
            ["2024-01-01", 9.0, 10.0, 8.5, 9.5, 800, 8000],
        ])
        dividend = _make_dividend_df([])
        result = compute_qfq(raw, dividend)
        pd.testing.assert_frame_equal(result, raw)

    def test_empty_raw(self):
        raw = pd.DataFrame()
        dividend = _make_dividend_df([["2024-06-01", 5.0, 0, 0, "实施"]])
        result = compute_qfq(raw, dividend)
        assert result.empty

    def test_none_raw(self):
        result = compute_qfq(None, _make_dividend_df([]))
        assert result is None


class TestComputeQfqSingleCashDividend:
    def test_cash_only(self):
        raw = _make_raw_df([
            ["2024-01-04", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-03", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-02", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-01", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
        ])
        dividend = _make_dividend_df([
            ["2024-01-03", 5.0, 0, 0, "实施"],
        ])
        result = compute_qfq(raw, dividend)

        factor = (10.0 - 0.5) / (10.0 * 1.0)
        assert result.iloc[0]["close"] == 10.0
        assert result.iloc[1]["close"] == 10.0
        assert result.iloc[2]["close"] == round(10.0 * factor, 2)
        assert result.iloc[3]["close"] == round(10.0 * factor, 2)
        assert result.iloc[0]["volume"] == 1000
        assert result.iloc[3]["volume"] == 1000


class TestComputeQfqBonusShares:
    def test_bonus_and_transfer(self):
        raw = _make_raw_df([
            ["2024-01-03", 20.0, 22.0, 18.0, 20.0, 1000, 10000],
            ["2024-01-02", 20.0, 22.0, 18.0, 20.0, 1000, 10000],
            ["2024-01-01", 20.0, 22.0, 18.0, 20.0, 1000, 10000],
        ])
        dividend = _make_dividend_df([
            ["2024-01-03", 2.0, 3.0, 2.0, "实施"],
        ])
        result = compute_qfq(raw, dividend)

        per_cash = 2.0 / 10
        per_bonus = 3.0 / 10
        per_transfer = 2.0 / 10
        factor = (20.0 - per_cash) / (20.0 * (1 + per_bonus + per_transfer))

        assert result.iloc[0]["close"] == 20.0
        assert result.iloc[1]["close"] == round(20.0 * factor, 2)
        assert result.iloc[2]["close"] == round(20.0 * factor, 2)


class TestComputeQfqMultipleDividends:
    def test_cumulative_factors(self):
        raw = _make_raw_df([
            ["2024-01-05", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-04", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-03", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-02", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-01", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
        ])
        dividend = _make_dividend_df([
            ["2024-01-04", 5.0, 0, 0, "实施"],
            ["2024-01-02", 10.0, 0, 0, "实施"],
        ])
        result = compute_qfq(raw, dividend)

        factor1 = (10.0 - 0.5) / 10.0
        factor2 = (10.0 - 1.0) / 10.0

        assert result.iloc[0]["close"] == 10.0
        assert result.iloc[1]["close"] == 10.0
        assert result.iloc[2]["close"] == round(10.0 * factor1, 2)
        assert result.iloc[3]["close"] == round(10.0 * factor1, 2)
        assert result.iloc[4]["close"] == round(10.0 * factor1 * factor2, 2)


class TestComputeQfqDescendingOrder:
    def test_preserves_descending_order(self):
        raw = _make_raw_df([
            ["2024-01-04", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-03", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-02", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-01", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
        ])
        dividend = _make_dividend_df([
            ["2024-01-03", 5.0, 0, 0, "实施"],
        ])
        result = compute_qfq(raw, dividend)
        assert result.iloc[0]["date"] == "2024-01-04"
        assert result.iloc[-1]["date"] == "2024-01-01"

    def test_ascending_order_input(self):
        raw = _make_raw_df([
            ["2024-01-01", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-02", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-03", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-04", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
        ])
        dividend = _make_dividend_df([
            ["2024-01-03", 5.0, 0, 0, "实施"],
        ])
        result = compute_qfq(raw, dividend)
        assert result.iloc[0]["date"] == "2024-01-01"
        assert result.iloc[-1]["date"] == "2024-01-04"


class TestComputeQfqNanHandling:
    def test_nan_dividend_fields_treated_as_zero(self):
        raw = _make_raw_df([
            ["2024-01-03", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-02", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
            ["2024-01-01", 10.0, 11.0, 9.0, 10.0, 1000, 10000],
        ])
        dividend = _make_dividend_df([
            ["2024-01-03", np.nan, np.nan, np.nan, "实施"],
        ])
        result = compute_qfq(raw, dividend)
        assert result.iloc[0]["close"] == 10.0
        assert result.iloc[1]["close"] == 10.0
        assert result.iloc[2]["close"] == 10.0


class TestGetLatestExDate:
    def test_returns_latest_ex_date(self):
        div_df = pd.DataFrame({
            "除权除息日": ["2024-06-12", "2025-10-15"],
            "方案进度": ["实施分配", "实施分配"],
            "现金分红-现金分红比例": [5.0, 2.0],
            "送转股份-送股比例": [0.0, 0.0],
            "送转股份-转股比例": [0.0, 0.0],
        })
        with tempfile.TemporaryDirectory() as tmp:
            div_dir = Path(tmp)
            div_df.to_parquet(div_dir / "000001.SZ.parquet", index=False)
            with patch("backend.services.qfq_cache.DIVIDEND_DIR", div_dir):
                result = get_latest_ex_date("000001.SZ")
                assert result == "2025-10-15"

    def test_returns_none_when_no_dividend(self):
        with tempfile.TemporaryDirectory() as tmp:
            div_dir = Path(tmp)
            with patch("backend.services.qfq_cache.DIVIDEND_DIR", div_dir):
                result = get_latest_ex_date("999999.SZ")
                assert result is None

    def test_returns_none_when_no_implemented(self):
        div_df = pd.DataFrame({
            "除权除息日": ["2024-06-12"],
            "方案进度": ["预案"],
            "现金分红-现金分红比例": [5.0],
            "送转股份-送股比例": [0.0],
            "送转股份-转股比例": [0.0],
        })
        with tempfile.TemporaryDirectory() as tmp:
            div_dir = Path(tmp)
            div_df.to_parquet(div_dir / "000001.SZ.parquet", index=False)
            with patch("backend.services.qfq_cache.DIVIDEND_DIR", div_dir):
                result = get_latest_ex_date("000001.SZ")
                assert result is None


class TestCacheManagement:
    def _setup_dirs(self):
        self.tmp = tempfile.mkdtemp()
        self.raw_dir = Path(self.tmp) / "raw"
        self.qfq_dir = Path(self.tmp) / "qfq"
        self.div_dir = Path(self.tmp) / "dividend"
        self.raw_dir.mkdir(parents=True)
        self.qfq_dir.mkdir(parents=True)
        self.div_dir.mkdir(parents=True)

        self.raw_df = pd.DataFrame({
            "date": ["2025-06-13", "2025-06-12", "2025-06-11"],
            "open": [9.6, 9.5, 10.0],
            "high": [9.8, 9.7, 10.2],
            "low": [9.4, 9.3, 9.8],
            "close": [9.6, 9.5, 10.0],
            "volume": [1200.0, 1100.0, 1000.0],
            "amount": [12000.0, 11000.0, 10000.0],
        })
        self.raw_df.to_parquet(self.raw_dir / "000001.SZ.parquet", index=False)

        self.div_df = pd.DataFrame({
            "除权除息日": ["2025-06-12"],
            "现金分红-现金分红比例": [5.0],
            "送转股份-送股比例": [0.0],
            "送转股份-转股比例": [0.0],
            "方案进度": ["实施分配"],
        })
        self.div_df.to_parquet(self.div_dir / "000001.SZ.parquet", index=False)

    def test_get_qfq_kline_computes_and_caches(self):
        self._setup_dirs()
        meta_file = self.qfq_dir / "_meta.json"

        with patch("backend.services.qfq_cache.RAW_KLINE_DIR", self.raw_dir), \
             patch("backend.services.qfq_cache.QFQ_KLINE_DIR", self.qfq_dir), \
             patch("backend.services.qfq_cache.DIVIDEND_DIR", self.div_dir), \
             patch("backend.services.qfq_cache.QFQ_META_FILE", meta_file):
            result = get_qfq_kline("000001.SZ")
            assert not result.empty
            assert (self.qfq_dir / "000001.SZ.parquet").exists()
            assert meta_file.exists()
            meta = json.loads(meta_file.read_text())
            assert "000001.SZ" in meta
            assert meta["000001.SZ"]["raw_latest_date"] == "2025-06-13"

    def test_get_qfq_kline_uses_cache_on_second_call(self):
        self._setup_dirs()
        meta_file = self.qfq_dir / "_meta.json"

        with patch("backend.services.qfq_cache.RAW_KLINE_DIR", self.raw_dir), \
             patch("backend.services.qfq_cache.QFQ_KLINE_DIR", self.qfq_dir), \
             patch("backend.services.qfq_cache.DIVIDEND_DIR", self.div_dir), \
             patch("backend.services.qfq_cache.QFQ_META_FILE", meta_file):
            result1 = get_qfq_kline("000001.SZ")
            result2 = get_qfq_kline("000001.SZ")
            pd.testing.assert_frame_equal(result1, result2)

    def test_get_qfq_kline_with_date_filter(self):
        self._setup_dirs()
        meta_file = self.qfq_dir / "_meta.json"

        with patch("backend.services.qfq_cache.RAW_KLINE_DIR", self.raw_dir), \
             patch("backend.services.qfq_cache.QFQ_KLINE_DIR", self.qfq_dir), \
             patch("backend.services.qfq_cache.DIVIDEND_DIR", self.div_dir), \
             patch("backend.services.qfq_cache.QFQ_META_FILE", meta_file):
            result = get_qfq_kline("000001.SZ", start_date="2025-06-12")
            assert len(result) == 2
            assert result.iloc[0]["date"] >= "2025-06-12"

    def test_invalidate_cache_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            qfq_dir = Path(tmp)
            cache_file = qfq_dir / "000001.SZ.parquet"
            cache_file.write_text("dummy")
            meta_file = qfq_dir / "_meta.json"
            meta_file.write_text(json.dumps({"000001.SZ": {"last_ex_date": "2025-06-12", "raw_latest_date": "2025-06-13"}}))

            with patch("backend.services.qfq_cache.QFQ_KLINE_DIR", qfq_dir), \
                 patch("backend.services.qfq_cache.QFQ_META_FILE", meta_file):
                invalidate_cache(["000001.SZ"])
                assert not cache_file.exists()
                meta = json.loads(meta_file.read_text())
                assert "000001.SZ" not in meta

    def test_invalidate_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            qfq_dir = Path(tmp)
            (qfq_dir / "000001.SZ.parquet").write_text("a")
            (qfq_dir / "000002.SZ.parquet").write_text("b")
            meta_file = qfq_dir / "_meta.json"
            meta_file.write_text(json.dumps({"000001.SZ": {}, "000002.SZ": {}}))

            with patch("backend.services.qfq_cache.QFQ_KLINE_DIR", qfq_dir), \
                 patch("backend.services.qfq_cache.QFQ_META_FILE", meta_file):
                invalidate_all()
                assert not list(qfq_dir.glob("*.parquet"))
                meta = json.loads(meta_file.read_text())
                assert meta == {}

    def test_get_qfq_kline_returns_empty_for_missing_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw"
            raw_dir.mkdir()
            qfq_dir = Path(tmp) / "qfq"
            qfq_dir.mkdir()
            meta_file = qfq_dir / "_meta.json"

            with patch("backend.services.qfq_cache.RAW_KLINE_DIR", raw_dir), \
                 patch("backend.services.qfq_cache.QFQ_KLINE_DIR", qfq_dir), \
                 patch("backend.services.qfq_cache.QFQ_META_FILE", meta_file):
                result = get_qfq_kline("NONEXIST.SZ")
                assert result.empty
