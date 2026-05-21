"""
data_cache 加载与切片测试。

替代旧 routers.backtest._load_stock_data 的覆盖(那个函数已删除,
全市场缓存通过 services.backtest.data_cache 提供)。

覆盖点:
- _load_stock_data_full(market) 经 DuckDBStore 拉全市场全历史 K 线
- HK 市场视图正常工作
- slice_bundle 按 symbols 子集切片
- slice_bundle 按 start/end 日期切片(只切 K 线,估值/分红/财务保持全量)
"""

import pandas as pd
import pytest

from services.duckdb_store import DuckDBStore
import services.duckdb_store as duckdb_store_module
import services.backtest.data_cache as data_cache


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
    # data_cache._load_stock_data_full 内部用 get_store(),指向我们这个临时 store
    monkeypatch.setattr(data_cache, "get_store", lambda: s)
    yield s, market_dir
    s.close()


def _rebuild(s):
    s._setup_views()


SAMPLE_ROWS = [
    ("2024-01-02", 10.0, 10.5, 9.5, 10.0, 100, 1000.0),
    ("2024-02-02", 11.0, 11.5, 10.5, 11.0, 100, 1100.0),
    ("2024-03-02", 12.0, 12.5, 11.5, 12.0, 100, 1200.0),
]


def test_load_full_market_A(patched_store):
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _write_daily(mdir, "A", "000002.SZ", SAMPLE_ROWS)
    _rebuild(s)

    out = data_cache._load_stock_data_full("A")
    assert set(out.keys()) == {"000001.SZ", "000002.SZ"}
    assert len(out["000001.SZ"]) == 3


def test_load_full_market_HK(patched_store):
    s, mdir = patched_store
    _write_daily(mdir, "A", "000001.SZ", SAMPLE_ROWS)
    _write_daily(mdir, "HK", "00700.HK", SAMPLE_ROWS)
    _rebuild(s)

    out = data_cache._load_stock_data_full("HK")
    assert set(out.keys()) == {"00700.HK"}


def _make_bundle(symbols: list[str]) -> data_cache.MarketBundle:
    stock = {}
    for sym in symbols:
        stock[sym] = pd.DataFrame(
            SAMPLE_ROWS,
            columns=[
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
            ],
        )
    return data_cache.MarketBundle(market="A", stock_data=stock)


def test_slice_by_symbols_subset():
    bundle = _make_bundle(["000001.SZ", "000002.SZ", "000003.SZ"])
    stock, _, _, _ = data_cache.slice_bundle(
        bundle, ["000001.SZ", "000002.SZ"], None, None
    )
    assert set(stock.keys()) == {"000001.SZ", "000002.SZ"}


def test_slice_by_symbols_none_returns_all():
    bundle = _make_bundle(["000001.SZ", "000002.SZ"])
    stock, _, _, _ = data_cache.slice_bundle(bundle, None, None, None)
    assert set(stock.keys()) == {"000001.SZ", "000002.SZ"}


def test_slice_by_date_range():
    bundle = _make_bundle(["000001.SZ"])
    stock, _, _, _ = data_cache.slice_bundle(bundle, None, "2024-02-01", "2024-02-28")
    assert len(stock["000001.SZ"]) == 1
    assert stock["000001.SZ"]["date"].tolist() == ["2024-02-02"]


def test_slice_unknown_symbol_skipped():
    bundle = _make_bundle(["000001.SZ"])
    stock, _, _, _ = data_cache.slice_bundle(
        bundle, ["000001.SZ", "NOPE.SZ"], None, None
    )
    assert set(stock.keys()) == {"000001.SZ"}
