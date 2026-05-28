"""DuckDB raw 视图回归测试 — 锁定三市场 21 个 raw 视图存在、有数据、含 join key。

Phase 1a 验收测试。Phase 1b(业务视图)前置防回归保险。
跑在真实 data/market/ 上,缺数据则 skip(CI 友好)。
"""

import pytest

from config import MARKET_DIR
from services.duckdb_store import DuckDBStore

MARKETS = ["a", "hk", "us"]
PERIODIC_TABLES = ["indicator", "income", "balance", "cashflow"]
# adjust_factor 用 BaoStock 原生字段 dividOperateDate(事件日)而非 date,单独断言
DAILY_TABLES = ["daily", "dividend"]
ALL_TABLES = PERIODIC_TABLES + DAILY_TABLES + ["adjust_factor"]


def _has_real_data() -> bool:
    """A 股 daily/financial 都得在,否则 skip。"""
    a = MARKET_DIR / "A"
    return (
        (a / "daily").exists()
        and any((a / "daily").glob("*.parquet"))
        and (a / "financial" / "income").exists()
        and any((a / "financial" / "income").glob("*.parquet"))
    )


@pytest.fixture(scope="module")
def store():
    if not _has_real_data():
        pytest.skip("无真实 data/market 数据,跳过 raw 视图回归测试")
    return DuckDBStore()


@pytest.mark.parametrize(
    "view_name",
    [f"v_{m}_{t}" for m in MARKETS for t in ALL_TABLES],
)
def test_raw_view_exists_and_nonempty(store, view_name):
    """每个 raw 视图必须存在且至少有 1 行数据。"""
    n = store._conn.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
    assert n > 0, f"{view_name} 行数为 0"


@pytest.mark.parametrize("market", MARKETS)
@pytest.mark.parametrize("table", PERIODIC_TABLES)
def test_periodic_view_has_join_keys(store, market, table):
    """财务/指标视图必须有 _symbol + REPORT_DATE(业务视图 ASOF JOIN 依赖)。"""
    view = f"v_{market}_{table}"
    cols = store._conn.execute(f"DESCRIBE {view}").fetchdf()["column_name"].tolist()
    assert "_symbol" in cols, f"{view} 缺 _symbol"
    assert "REPORT_DATE" in cols, f"{view} 缺 REPORT_DATE"


@pytest.mark.parametrize("market", MARKETS)
@pytest.mark.parametrize("table", DAILY_TABLES)
def test_daily_view_has_join_keys(store, market, table):
    """日线/分红视图必须有 _symbol + date。"""
    view = f"v_{market}_{table}"
    cols = store._conn.execute(f"DESCRIBE {view}").fetchdf()["column_name"].tolist()
    assert "_symbol" in cols, f"{view} 缺 _symbol"
    assert "date" in cols, f"{view} 缺 date"


@pytest.mark.parametrize("market", MARKETS)
def test_adjust_factor_view_has_join_keys(store, market):
    """复权因子视图保持 BaoStock 原生 schema:_symbol + dividOperateDate(除权日)。"""
    view = f"v_{market}_adjust_factor"
    cols = store._conn.execute(f"DESCRIBE {view}").fetchdf()["column_name"].tolist()
    assert "_symbol" in cols, f"{view} 缺 _symbol"
    assert "dividOperateDate" in cols, f"{view} 缺 dividOperateDate"


def test_a_indicator_has_legacy_eastmoney_fields(store):
    """A 股 indicator 必须保留 EastMoney 拼音字段(业务视图层会翻译,但 raw 层不动)。"""
    cols = (
        store._conn.execute("DESCRIBE v_a_indicator").fetchdf()["column_name"].tolist()
    )
    # PARENTNETPROFIT 是 A 股独有,业务视图层 fallback 用
    for c in ("PARENTNETPROFIT", "EPSJB", "TOTAL_SHARE"):
        assert c in cols, f"v_a_indicator 缺 {c}"


def test_hk_us_indicator_thin_schema(store):
    """HK/US indicator 是 IFRS 瘦 schema,不该有 A 股独有字段(锚定差异)。"""
    for market in ("hk", "us"):
        cols = (
            store._conn.execute(f"DESCRIBE v_{market}_indicator")
            .fetchdf()["column_name"]
            .tolist()
        )
        assert "PARENTNETPROFIT" not in cols, (
            f"v_{market}_indicator 不应有 A 股拼音字段 PARENTNETPROFIT"
        )
