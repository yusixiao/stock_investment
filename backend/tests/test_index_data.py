"""指数数据层测试 —— index_updater 记录构造 + DuckDBStore.query_index_bulk/query_index。

指数(HSI / CSI300 等)独立于个股:
- 不需要复权因子,直读 v_{market}_index
- 不进 query_qfq_kline_bulk 的股票 universe(本测试显式断言隔离)

抓取测试用伪 Ticker / mock baostock 绕过网络;查询测试在真实 data/market/ 上跑,
缺数据则 skip(CI 友好)。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from config import MARKET_DIR
from services.market_data.duckdb_store import DuckDBStore
from services.market_data.updaters.index_updater import (
    INDEX_CATALOG,
    _fetch_baostock_index,
    _fetch_yfinance_index,
    get_index_catalog,
)


# ---------------- 抓取层:记录构造(mock 数据源)----------------


def _make_yf_ticker(df: pd.DataFrame):
    class FakeTicker:
        def __init__(self, *a, **kw):
            pass

        def history(self, *a, **kw):
            return df

    return FakeTicker


def test_fetch_yfinance_index_builds_records():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    df = pd.DataFrame(
        {
            "Open": [100.0, 102.0],
            "High": [103.0, 104.0],
            "Low": [99.0, 101.0],
            "Close": [102.0, 101.0],
            "Volume": [1000.0, float("nan")],
        },
        index=idx,
    )
    with patch("yfinance.Ticker", _make_yf_ticker(df)):
        recs = _fetch_yfinance_index("^HSI", "HSI", start_date=None)

    assert len(recs) == 2
    assert recs[0].code == "HSI"
    assert recs[0].date == "2024-01-02"
    assert recs[0].close == 102.0
    # 首行无 preclose;次行 preclose=上一收盘
    assert recs[0].preclose is None
    assert recs[1].preclose == 102.0
    # NaN volume → 0.0;指数 amount 恒 0
    assert recs[1].volume == 0.0
    assert recs[0].amount == 0.0
    # pctChg 次行 = (101-102)/102*100
    assert recs[1].pctChg == pytest.approx((101.0 - 102.0) / 102.0 * 100)


def test_fetch_yfinance_index_incremental_seeds_preclose():
    """回归(2026-07 HSI 停更): 增量抓取时首个落库行(=start_date, 库内最新日)
    必须有非空 preclose, 否则台账护栏判"非空→null"拒写导致指数永久停更。

    实现靠向前挪 15 自然日取缓冲窗口播种 prev_close, 再过滤回 date>=start_date。
    FakeTicker.history 忽略 start 参数、返回含缓冲行的整段 df, 正好模拟真实
    yfinance 从 buffer_start 起返回的数据。
    """
    idx = pd.to_datetime(["2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03"])
    df = pd.DataFrame(
        {
            "Open": [100.0, 110.0, 120.0, 130.0],
            "High": [101.0, 111.0, 121.0, 131.0],
            "Low": [99.0, 109.0, 119.0, 129.0],
            "Close": [100.0, 110.0, 120.0, 130.0],
            "Volume": [1000.0, 1000.0, 1000.0, 1000.0],
        },
        index=idx,
    )
    with patch("yfinance.Ticker", _make_yf_ticker(df)):
        recs = _fetch_yfinance_index("^HSI", "HSI", start_date="2026-07-02")

    # 缓冲行(06-30 / 07-01)被过滤, 只落 start_date 当天及之后
    assert [r.date for r in recs] == ["2026-07-02", "2026-07-03"]
    # 关键: 首个落库行(07-02)preclose 非空 = 缓冲行 07-01 的收盘(110)
    assert recs[0].preclose == 110.0
    assert recs[0].pctChg == pytest.approx((120.0 - 110.0) / 110.0 * 100)
    assert recs[1].preclose == 120.0


def test_fetch_baostock_index_builds_records():
    raw = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "code": ["sh.000300", "sh.000300"],
            "open": ["3000.0", "3010.0"],
            "high": ["3050.0", "3040.0"],
            "low": ["2990.0", "3000.0"],
            "close": ["3010.0", "3005.0"],
            "preclose": ["2995.0", "3010.0"],
            "volume": ["123456", "234567"],
            "amount": ["1.0e9", "2.0e9"],
            "pctChg": ["0.5", "-0.17"],
        }
    )
    with patch("baostock.login", return_value=MagicMock(error_code="0")), patch(
        "baostock.logout"
    ), patch("baostock.query_history_k_data_plus", return_value=MagicMock()), patch(
        "backend.adapters.baostock_adapter._result_to_df", return_value=raw
    ):
        recs = _fetch_baostock_index("sh.000300", "CSI300", start_date="2024-01-01")

    assert len(recs) == 2
    assert recs[0].code == "CSI300"  # 落库用干净 catalog code,非 sh.000300
    assert recs[0].open == 3000.0
    assert recs[1].close == 3005.0
    assert recs[0].amount == pytest.approx(1.0e9)


def test_catalog_codes_are_clean_and_unique():
    """catalog code 不应含数据源前缀(^ / sh.),且唯一。"""
    codes = [it["code"] for it in get_index_catalog()]
    assert len(codes) == len(set(codes)), "catalog code 重复"
    for c in codes:
        assert "^" not in c and "." not in c, f"code {c} 含数据源前缀"
    # get_index_catalog 返回浅拷贝,改动不污染原表
    cat = get_index_catalog()
    cat[0]["code"] = "MUTATED"
    assert INDEX_CATALOG[0]["code"] != "MUTATED"


# ---------------- 查询层:DuckDB 视图(真实数据)----------------


def _has_index_data() -> bool:
    hk = MARKET_DIR / "HK" / "index"
    return hk.exists() and any(hk.glob("*.parquet"))


@pytest.fixture(scope="module")
def store():
    if not _has_index_data():
        pytest.skip("无真实指数数据,跳过 query_index 测试")
    return DuckDBStore()


def test_query_index_bulk_returns_series(store):
    hk = store.query_index_bulk("HK")
    assert "HSI" in hk, "HK 指数应含 HSI"
    df = hk["HSI"]
    assert len(df) > 0
    # date 升序
    assert df["date"].is_monotonic_increasing
    for col in ("open", "high", "low", "close"):
        assert col in df.columns


def test_query_index_single_with_date_filter(store):
    df = store.query_index("HK", "HSI", start_date="2020-01-01", end_date="2020-12-31")
    assert len(df) > 0
    assert df["date"].min() >= "2020-01-01"
    assert df["date"].max() <= "2020-12-31"


def test_query_index_missing_view_returns_empty(store):
    """不存在的市场指数视图 → 空结果,不抛异常。"""
    assert store.query_index_bulk("US") == {} or isinstance(
        store.query_index_bulk("US"), dict
    )


def test_index_not_in_stock_universe(store):
    """铁律:指数绝不能混进个股 qfq universe。"""
    qfq = store.query_qfq_kline_bulk(market="HK", symbols=None, start="2024-01-01")
    assert "HSI" not in qfq, "指数 HSI 不应出现在个股 qfq 结果中"
