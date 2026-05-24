"""DuckDBStore 冷热分层 hot-path 测试。

设计:
- DuckDB 视图为空(冷数据无),正常情况这些方法会返回 []/empty
- patch data_cache.get_market 返回带样本数据的 MarketBundle → hot-path 应直接命中 bundle 返回
- 这就证明业务 API 在 bundle 已加载时不再触发 DuckDB SQL
- bundle 为 None / 缺数据时,自动降级到 DuckDB(空视图 → 空结果),即原有行为不破坏
"""

from __future__ import annotations

import pandas as pd
import pytest

from services.duckdb_store import DuckDBStore
import services.duckdb_store as duckdb_store_module
from services.backtest.data_cache import MarketBundle


def _write_empty_daily(market_dir, market, symbol="000001.SZ"):
    """写一个最小 daily parquet 让视图能创建。"""
    d = market_dir / market / "daily"
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        [["2099-01-01", 1.0, 1.0, 1.0, 1.0, 100, 100.0]],
        columns=["date", "open", "high", "low", "close", "volume", "amount"],
    )
    df["code"] = symbol
    df = df[["code", "date", "open", "high", "low", "close", "volume", "amount"]]
    df.to_parquet(d / f"{symbol}.parquet", index=False)


@pytest.fixture
def empty_store(tmp_path, monkeypatch):
    """指向空数据(只有 placeholder 视图)的 DuckDBStore — 冷路径返回空。"""
    market_dir = tmp_path / "market"
    for m in ("A", "HK", "US"):
        _write_empty_daily(market_dir, m)
    monkeypatch.setattr(duckdb_store_module, "MARKET_DIR", market_dir)
    s = DuckDBStore()
    yield s
    s.close()


def _patch_bundle(monkeypatch, market: str, bundle: MarketBundle | None):
    """patch data_cache.get_market 返回指定 bundle。"""

    def fake_get_market(m: str):
        return bundle if m.upper() == market.upper() else None

    monkeypatch.setattr("services.backtest.data_cache.get_market", fake_get_market)


# ---------- query_qfq_kline ----------


def test_qfq_kline_hits_bundle_when_loaded(empty_store, monkeypatch):
    code = "600000.SH"
    df = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, 10.5, 11.0],
            "high": [10.8, 11.0, 11.5],
            "low": [9.8, 10.3, 10.8],
            "close": [10.5, 10.8, 11.2],
            "volume": [1000, 2000, 1500],
            "amount": [10500.0, 21600.0, 16800.0],
            "ma5": [10.5, 10.65, 10.83],  # 多余指标列,公开方法应去掉
        }
    )
    bundle = MarketBundle(market="A", stock_data={code: df})
    _patch_bundle(monkeypatch, "A", bundle)

    out = empty_store.query_qfq_kline("A", code)

    assert not out.empty, "bundle 已加载时应命中 hot-path"
    assert list(out.columns) == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert len(out) == 3
    assert out.iloc[0]["close"] == 10.5


def test_qfq_kline_filters_date_range_in_bundle(empty_store, monkeypatch):
    code = "600000.SH"
    df = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
            "open": [10.0, 10.5, 11.0, 11.2],
            "high": [10.8, 11.0, 11.5, 11.6],
            "low": [9.8, 10.3, 10.8, 11.0],
            "close": [10.5, 10.8, 11.2, 11.5],
            "volume": [1000, 2000, 1500, 1800],
            "amount": [10500.0, 21600.0, 16800.0, 20700.0],
        }
    )
    bundle = MarketBundle(market="A", stock_data={code: df})
    _patch_bundle(monkeypatch, "A", bundle)

    out = empty_store.query_qfq_kline("A", code, start="2024-01-03", end="2024-01-04")

    assert len(out) == 2
    assert out.iloc[0]["date"] == "2024-01-03"
    assert out.iloc[1]["date"] == "2024-01-04"


def test_qfq_kline_falls_back_when_bundle_missing(empty_store, monkeypatch):
    """bundle 没有该 symbol → 冷路径(空 DuckDB 返回空 DataFrame)。"""
    bundle = MarketBundle(market="A", stock_data={})
    _patch_bundle(monkeypatch, "A", bundle)

    out = empty_store.query_qfq_kline("A", "600000.SH")

    assert out.empty


def test_qfq_kline_falls_back_when_bundle_not_loaded(empty_store, monkeypatch):
    """bundle 完全未加载 → get_market 返回 None → 冷路径。"""
    _patch_bundle(monkeypatch, "A", None)

    out = empty_store.query_qfq_kline("A", "600000.SH")

    assert out.empty  # 冷 DuckDB 也是空


# ---------- query_qfq_kline_for_section ----------


def test_qfq_kline_for_section_daily_hits_bundle(empty_store, monkeypatch):
    code = "600000.SH"
    df = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, 10.5, 11.0],
            "high": [10.8, 11.0, 11.5],
            "low": [9.8, 10.3, 10.8],
            "close": [10.5, 10.8, 11.2],
            "volume": [1000, 2000, 1500],
            "amount": [10500.0, 21600.0, 16800.0],
        }
    )
    bundle = MarketBundle(market="A", stock_data={code: df})
    _patch_bundle(monkeypatch, "A", bundle)

    rows = empty_store.query_qfq_kline_for_section(code, limit=1, order="desc")

    assert len(rows) == 1
    assert rows[0]["date"] == "2024-01-04"
    assert rows[0]["close"] == 11.2


def test_qfq_kline_for_section_weekly_hits_bundle(empty_store, monkeypatch):
    code = "600000.SH"
    weekly = pd.DataFrame(
        {
            "date": ["2024-01-05", "2024-01-12"],
            "open": [10.0, 11.0],
            "high": [11.5, 12.0],
            "low": [9.8, 10.8],
            "close": [11.2, 11.8],
            "volume": [5000, 4000],
            "amount": [56000.0, 47200.0],
        }
    )
    bundle = MarketBundle(
        market="A", stock_data={code: pd.DataFrame()}, weekly_data={code: weekly}
    )
    _patch_bundle(monkeypatch, "A", bundle)

    rows = empty_store.query_qfq_kline_for_section(code, freq="W", years=5)

    assert len(rows) == 2
    assert rows[0]["date"] == "2024-01-05"


# ---------- query_dividend_for_section ----------


def test_dividend_for_section_hits_bundle(empty_store, monkeypatch):
    code = "600000.SH"
    div = pd.DataFrame(
        {
            "date": ["2022-06-15", "2023-06-20", "2024-06-10", "2024-12-15"],
            "cash_dividend": [0.3, 0.4, 0.25, 0.15],
        }
    )
    bundle = MarketBundle(market="A", stock_data={}, dividend_data={code: div})
    _patch_bundle(monkeypatch, "A", bundle)

    rows = empty_store.query_dividend_for_section(code, years=5)

    by_year = {r["year"]: r["dps"] for r in rows}
    assert by_year[2024] == pytest.approx(0.4)  # 0.25 + 0.15
    assert by_year[2023] == pytest.approx(0.4)
    assert by_year[2022] == pytest.approx(0.3)
    # 应按年降序
    years = [r["year"] for r in rows]
    assert years == sorted(years, reverse=True)


def test_dividend_for_section_respects_years_limit(empty_store, monkeypatch):
    code = "600000.SH"
    div = pd.DataFrame(
        {
            "date": [f"{y}-06-15" for y in (2019, 2020, 2021, 2022, 2023, 2024)],
            "cash_dividend": [0.1] * 6,
        }
    )
    bundle = MarketBundle(market="A", stock_data={}, dividend_data={code: div})
    _patch_bundle(monkeypatch, "A", bundle)

    rows = empty_store.query_dividend_for_section(code, years=3)

    assert len(rows) == 3
    assert [r["year"] for r in rows] == [2024, 2023, 2022]


# ---------- query_financial_for_section(indicator) ----------


def test_financial_indicator_hits_bundle(empty_store, monkeypatch):
    code = "600000.SH"
    fin = pd.DataFrame(
        {
            "REPORT_DATE": [
                "2024-12-31",
                "2024-09-30",  # Q3 累计,应被过滤(只看年报)
                "2023-12-31",
                "2022-12-31",
            ],
            "ROEJQ": [10.5, 6.7, 11.2, 12.0],
            "ZZCJLL": [5.0, 3.0, 5.5, 6.0],
            "XSMLL": [25.0, 24.0, 26.0, 27.0],
            "XSJLL": [12.0, 10.0, 13.0, 14.0],
            "ZCFZL": [60.0, 61.0, 59.0, 58.0],
            "LD": [1.5, 1.4, 1.6, 1.7],
            "BPS": [8.0, 7.8, 7.5, 7.0],
            "EPSJB": [1.2, 0.7, 1.3, 1.4],
        }
    )
    bundle = MarketBundle(market="A", stock_data={}, financial_data={code: fin})
    _patch_bundle(monkeypatch, "A", bundle)

    rows = empty_store.query_financial_for_section(code, table="indicator", years=5)

    # 只取年报
    dates = [r["REPORT_DATE"] for r in rows]
    assert all(d.endswith("-12-31") for d in dates)
    assert dates == ["2024-12-31", "2023-12-31", "2022-12-31"]
    # 字段映射
    r0 = rows[0]
    assert r0["ROEJQ"] == 10.5
    assert r0["ROAJQ"] == 5.0
    assert r0["GROSSPROFIT_MARGIN"] == 25.0
    assert r0["NETPROFIT_MARGIN"] == 12.0
    assert r0["DEBT_ASSET_RATIO"] == 60.0
    assert r0["CURRENT_RATIO"] == 1.5
    assert r0["BPS"] == 8.0
    assert r0["EPSJB"] == 1.2


def test_financial_indicator_falls_back_when_no_bundle(empty_store, monkeypatch):
    _patch_bundle(monkeypatch, "A", None)
    rows = empty_store.query_financial_for_section(
        "600000.SH", table="indicator", years=5
    )
    assert rows == []


def test_financial_other_tables_not_handled_by_bundle(empty_store, monkeypatch):
    """income/balance/cashflow 当前不在 bundle 中,应直接走 DuckDB(空视图返回 [])。"""
    code = "600000.SH"
    bundle = MarketBundle(market="A", stock_data={})
    _patch_bundle(monkeypatch, "A", bundle)

    for tbl in ("income", "balance", "cashflow"):
        rows = empty_store.query_financial_for_section(code, table=tbl, years=5)
        assert rows == []  # bundle 不含,DuckDB 空 → []
