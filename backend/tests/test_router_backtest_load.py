"""
Tests for routers.backtest._load_stock_data (Phase 4.5, D8-A).

Validates that _load_stock_data uses DuckDBStore (not RAW_KLINE_DIR.glob) for:
- 个股模式 (symbols=[...])
- 全市场模式 (symbols=None / [])
- HK 市场
- 不存在的 symbol 跳过
- start/end=None 不限制
"""

import pandas as pd
import pytest

from services.duckdb_store import DuckDBStore
import services.duckdb_store as duckdb_store_module
import routers.backtest as backtest_router


def _write_daily(market_dir, market, symbol, rows):
    d = market_dir / market / "daily"
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close", "volume", "amount"],
    )
    df["code"] = symbol
    df = df[["code", "date", "open", "high", "low", "close", "volume", "amount"]]
    df.to_parquet(d / f"{symbol}.parquet", index=False)


@pytest.fixture
def patched_store(tmp_path, monkeypatch):
    market_dir = tmp_path / "market"
    for m in ("A", "HK", "US"):
        (market_dir / m / "daily").mkdir(parents=True, exist_ok=True)
        (market_dir / m / "adjust_factor").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(duckdb_store_module, "MARKET_DIR", market_dir)
    s = DuckDBStore()
    # 让 routers.backtest.get_store() 在测试中返回我们的临时 store
    monkeypatch.setattr(backtest_router, "get_store", lambda: s)
    yield s, market_dir
    s.close()


def _rebuild(s):
    s._setup_views()


SAMPLE_ROWS = [
    ("2024-01-02", 10.0, 10.5, 9.5, 10.0, 100, 1000.0),
    ("2024-02-02", 11.0, 11.5, 10.5, 11.0, 100, 1100.0),
    ("2024-03-02", 12.0, 12.5, 11.5, 12.0, 100, 1200.0),
]


def test_specific_symbols_returns_only_requested(patched_store):
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _write_daily(mdir, "A", "000002.SZ", SAMPLE_ROWS)
    _write_daily(mdir, "A", "000003.SZ", SAMPLE_ROWS)
    _rebuild(s)

    out = backtest_router._load_stock_data(None, None, ["000001.SZ", "000002.SZ"])
    assert set(out.keys()) == {"000001.SZ", "000002.SZ"}
    assert len(out["000001.SZ"]) == 3


def test_full_market_when_symbols_none(patched_store):
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _write_daily(mdir, "A", "000002.SZ", SAMPLE_ROWS)
    _rebuild(s)

    out = backtest_router._load_stock_data(None, None, None)
    assert set(out.keys()) == {"000001.SZ", "000002.SZ"}


def test_full_market_when_symbols_empty(patched_store):
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _rebuild(s)

    out = backtest_router._load_stock_data(None, None, [])
    assert set(out.keys()) == {"000001.SZ"}


def test_hk_market(patched_store):
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _write_daily(mdir, "HK", "00700.HK", SAMPLE_ROWS)
    _rebuild(s)

    out = backtest_router._load_stock_data(None, None, None, market="HK")
    assert set(out.keys()) == {"00700.HK"}


def test_missing_symbol_skipped(patched_store):
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _rebuild(s)

    out = backtest_router._load_stock_data(None, None, ["000001.SZ", "NOPE.SZ"])
    assert set(out.keys()) == {"000001.SZ"}


def test_start_end_filtering(patched_store):
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _rebuild(s)

    out = backtest_router._load_stock_data("2024-02-01", "2024-02-28", ["000001.SZ"])
    assert len(out["000001.SZ"]) == 1
    assert out["000001.SZ"]["date"].tolist() == ["2024-02-02"]


def test_default_market_is_A(patched_store):
    """不传 market 时默认用 A 市场（向后兼容）"""
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _write_daily(mdir, "HK", "00700.HK", SAMPLE_ROWS)
    _rebuild(s)

    out = backtest_router._load_stock_data(None, None, None)
    assert set(out.keys()) == {"000001.SZ"}
