import pandas as pd
import numpy as np
import pytest
from backend.services.qfq_cache import compute_qfq, _get_implemented_dividends


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
