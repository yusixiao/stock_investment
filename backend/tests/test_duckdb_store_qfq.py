"""
Tests for DuckDBStore.query_qfq_kline (Phase 4.1, D8-B step 1).

Validates ASOF JOIN with adjust_factor view to derive qfq prices on-the-fly
from raw daily parquet + adjust_factor parquet.
"""

import pandas as pd
import pytest

from services.market_data.duckdb_store import DuckDBStore
import services.market_data.duckdb_store as duckdb_store_module


def _write_daily(market_dir, market, symbol, rows):
    """rows = list of (date, open, high, low, close, volume, amount)"""
    d = market_dir / market / "daily"
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close", "volume", "amount"],
    )
    df["code"] = symbol
    df = df[["code", "date", "open", "high", "low", "close", "volume", "amount"]]
    df.to_parquet(d / f"{symbol}.parquet", index=False)


def _write_adjust(market_dir, market, symbol, rows):
    """rows = list of (dividOperateDate, foreAdjustFactor)"""
    d = market_dir / market / "adjust_factor"
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["dividOperateDate", "foreAdjustFactor"])
    df["code"] = symbol
    df["backAdjustFactor"] = 1.0
    df["adjustFactor"] = 1.0
    df = df[
        [
            "code",
            "dividOperateDate",
            "foreAdjustFactor",
            "backAdjustFactor",
            "adjustFactor",
        ]
    ]
    df.to_parquet(d / f"{symbol}.parquet", index=False)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """DuckDBStore pointed at tmp_path/market with empty layout."""
    market_dir = tmp_path / "market"
    for m in ("A", "HK", "US"):
        (market_dir / m / "daily").mkdir(parents=True, exist_ok=True)
        (market_dir / m / "adjust_factor").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(duckdb_store_module, "MARKET_DIR", market_dir)
    s = DuckDBStore()
    yield s, market_dir
    s.close()


def _rebuild(store):
    """Re-register views after writing parquet under the patched MARKET_DIR."""
    store._setup_views()


def test_no_adjust_returns_raw(store):
    s, mdir = store
    rows = [
        ("2024-01-02", 10.0, 11.0, 9.5, 10.5, 1000, 10500.0),
        ("2024-01-03", 10.5, 12.0, 10.0, 11.5, 1200, 13000.0),
    ]
    _write_daily(mdir, "A", "000001.SZ", rows)
    _rebuild(s)

    df = s.query_qfq_kline("A", "000001.SZ")
    assert len(df) == 2
    # No adjust factor → COALESCE 1.0 → raw prices
    assert df.iloc[0]["close"] == pytest.approx(10.5)
    assert df.iloc[1]["close"] == pytest.approx(11.5)


def test_single_dividend_event_scaling(store):
    s, mdir = store
    rows = [
        ("2024-01-02", 10.0, 10.0, 10.0, 10.0, 1000, 10000.0),  # before dividend
        ("2024-06-03", 10.0, 10.0, 10.0, 10.0, 1000, 10000.0),  # exactly on dividend
        ("2024-06-04", 10.0, 10.0, 10.0, 10.0, 1000, 10000.0),  # after dividend
    ]
    _write_daily(mdir, "A", "TEST.SZ", rows)
    # Single fore-adjust factor on 2024-06-03 = 0.95 (latest date factor)
    _write_adjust(mdir, "A", "TEST.SZ", [("2024-06-03", 0.95)])
    _rebuild(s)

    df = s.query_qfq_kline("A", "TEST.SZ")
    assert len(df) == 3
    df = df.set_index("date")
    # 2024-01-02: before any factor → COALESCE NULL → 1.0 → raw 10.0
    assert df.loc["2024-01-02", "close"] == pytest.approx(10.0)
    # On & after dividend: factor 0.95 → 10 * 0.95 = 9.5
    assert df.loc["2024-06-03", "close"] == pytest.approx(9.5)
    assert df.loc["2024-06-04", "close"] == pytest.approx(9.5)


def test_multiple_factors_asof_picks_latest(store):
    s, mdir = store
    rows = [
        ("2024-01-02", 10.0, 10.0, 10.0, 10.0, 100, 1000.0),
        ("2024-04-01", 10.0, 10.0, 10.0, 10.0, 100, 1000.0),
        ("2024-07-01", 10.0, 10.0, 10.0, 10.0, 100, 1000.0),
        ("2024-10-01", 10.0, 10.0, 10.0, 10.0, 100, 1000.0),
    ]
    _write_daily(mdir, "A", "M.SZ", rows)
    _write_adjust(
        mdir,
        "A",
        "M.SZ",
        [
            ("2024-03-15", 0.80),
            ("2024-06-15", 0.90),
            ("2024-09-15", 1.00),  # latest = 1.0 (qfq normalized)
        ],
    )
    _rebuild(s)

    df = s.query_qfq_kline("A", "M.SZ").set_index("date")
    assert df.loc["2024-01-02", "close"] == pytest.approx(10.0)  # before any factor
    assert df.loc["2024-04-01", "close"] == pytest.approx(8.0)  # 0.80
    assert df.loc["2024-07-01", "close"] == pytest.approx(9.0)  # 0.90
    assert df.loc["2024-10-01", "close"] == pytest.approx(10.0)  # 1.00


def test_start_end_slicing(store):
    s, mdir = store
    rows = [
        ("2024-01-02", 10.0, 10.0, 10.0, 10.0, 1, 10.0),
        ("2024-02-02", 11.0, 11.0, 11.0, 11.0, 1, 11.0),
        ("2024-03-02", 12.0, 12.0, 12.0, 12.0, 1, 12.0),
        ("2024-04-02", 13.0, 13.0, 13.0, 13.0, 1, 13.0),
    ]
    _write_daily(mdir, "A", "S.SZ", rows)
    _rebuild(s)

    df = s.query_qfq_kline("A", "S.SZ", start="2024-02-01", end="2024-03-15")
    assert len(df) == 2
    assert df["date"].tolist() == ["2024-02-02", "2024-03-02"]

    df_only_start = s.query_qfq_kline("A", "S.SZ", start="2024-03-01")
    assert df_only_start["date"].tolist() == ["2024-03-02", "2024-04-02"]

    df_only_end = s.query_qfq_kline("A", "S.SZ", end="2024-02-15")
    assert df_only_end["date"].tolist() == ["2024-01-02", "2024-02-02"]


def test_missing_symbol_returns_empty(store):
    s, mdir = store
    _write_daily(
        mdir,
        "A",
        "EXIST.SZ",
        [("2024-01-02", 10.0, 10.0, 10.0, 10.0, 1, 10.0)],
    )
    _rebuild(s)

    df = s.query_qfq_kline("A", "NOPE.SZ")
    assert df.empty
    df_empty = s.query_qfq_kline("A", "")
    assert df_empty.empty


def test_hk_view_mapping(store):
    s, mdir = store
    rows = [
        ("2024-01-02", 100.0, 100.0, 100.0, 100.0, 10, 1000.0),
        ("2024-06-03", 100.0, 100.0, 100.0, 100.0, 10, 1000.0),
    ]
    _write_daily(mdir, "HK", "00700.HK", rows)
    _write_adjust(mdir, "HK", "00700.HK", [("2024-06-03", 0.5)])
    _rebuild(s)

    df = s.query_qfq_kline("HK", "00700.HK").set_index("date")
    # before dividend → raw
    assert df.loc["2024-01-02", "close"] == pytest.approx(100.0)
    # on dividend → factor 0.5
    assert df.loc["2024-06-03", "close"] == pytest.approx(50.0)


def test_columns_dtypes_and_ascending_order(store):
    s, mdir = store
    rows = [
        ("2024-03-02", 12.0, 12.5, 11.5, 12.0, 100, 1200.0),
        ("2024-01-02", 10.0, 10.5, 9.5, 10.0, 100, 1000.0),
        ("2024-02-02", 11.0, 11.5, 10.5, 11.0, 100, 1100.0),
    ]
    _write_daily(mdir, "A", "C.SZ", rows)
    _rebuild(s)

    df = s.query_qfq_kline("A", "C.SZ")
    assert list(df.columns) == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    # ascending date order
    assert df["date"].tolist() == ["2024-01-02", "2024-02-02", "2024-03-02"]
    for col in ("open", "high", "low", "close"):
        assert pd.api.types.is_float_dtype(df[col])
