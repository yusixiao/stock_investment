"""业务视图层回归测试 — v_{market}_periodic_report。

Phase 1b 验收 + 防回归。锚定:
  1. 三市场视图都能建出且行数 = indicator 主表(LEFT JOIN 不丢行)
  2. 50 列 schema 对齐(三市场列名一致)
  3. strategies/utils 实际用到的字段都存在
  4. 同义字段统一(MONETARYFUNDS / CAPEX / CONSTRUCT_LONG_ASSET 别名)
  5. A 独有字段在 HK/US 上 NULL 占位但列存在
"""

import pytest

from config import MARKET_DIR
from services.duckdb_store import DuckDBStore

MARKETS = ["a", "hk", "us"]

# strategies/utils/conservative.py + valuation.py + financial.py 实际访问的字段
STRATEGY_USED_FIELDS = {
    # indicator 共有(三市场)
    "EPSJB",
    "ROEJQ",
    "ROA",
    "BPS",
    "XSMLL",
    # indicator A 独有(HK/US 视图必须有列名,值 NULL)
    "PARENTNETPROFIT",
    "TOTAL_SHARE",
    "FCFF_BACK",
    "PARENTNETPROFITTZ",
    # income 共有
    "PARENT_NETPROFIT",
    "NETPROFIT",
    "OPERATE_INCOME",
    "BASIC_EPS",
    # income 部分市场缺失但视图必须有列
    "TOTAL_OPERATE_INCOME",
    "DEDUCT_PARENT_NETPROFIT",
    # balance 共有
    "TOTAL_ASSETS",
    "TOTAL_LIABILITIES",
    "TOTAL_PARENT_EQUITY",
    # balance 同义统一
    "MONETARYFUNDS",
    "GOODWILL",
    "INDUSTRY_NAME",
    # cashflow 共有
    "NETCASH_OPERATE",
    "NETCASH_INVEST",
    "NETCASH_FINANCE",
    # cashflow 同义统一(双别名)
    "CAPEX",
    "CONSTRUCT_LONG_ASSET",
}


def _has_real_data() -> bool:
    a = MARKET_DIR / "A"
    return (a / "financial" / "indicator").exists() and any(
        (a / "financial" / "indicator").glob("*.parquet")
    )


@pytest.fixture(scope="module")
def store():
    if not _has_real_data():
        pytest.skip("无真实 data/market 数据")
    return DuckDBStore()


@pytest.mark.parametrize("market", MARKETS)
def test_periodic_report_view_exists(store, market):
    """业务视图必须建出且非空。"""
    view = f"v_{market}_periodic_report"
    n = store._conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
    assert n > 0, f"{view} rows = 0"


@pytest.mark.parametrize("market", MARKETS)
def test_periodic_report_left_join_preserves_indicator_rows(store, market):
    """LEFT JOIN indicator 主表 ⇒ 业务视图行数 = indicator 行数(不丢行)。"""
    biz = f"v_{market}_periodic_report"
    ind = f"v_{market}_indicator"
    n_biz = store._conn.execute(f"SELECT COUNT(*) FROM {biz}").fetchone()[0]
    n_ind = store._conn.execute(f"SELECT COUNT(*) FROM {ind}").fetchone()[0]
    assert n_biz == n_ind, f"{biz}({n_biz}) ≠ {ind}({n_ind}),LEFT JOIN 出错"


@pytest.mark.parametrize("market", MARKETS)
def test_periodic_report_has_all_strategy_fields(store, market):
    """strategies/utils 用到的全部字段在三市场业务视图中都必须存在(列名一致)。"""
    view = f"v_{market}_periodic_report"
    cols = set(
        store._conn.execute(f"DESCRIBE {view}").fetchdf()["column_name"].tolist()
    )
    missing = STRATEGY_USED_FIELDS - cols
    assert not missing, f"{view} 缺字段: {missing}"


def test_three_markets_have_aligned_schema(store):
    """三市场业务视图 schema 必须完全一致(列名 + 顺序)。"""
    schemas = {}
    for m in MARKETS:
        df = store._conn.execute(f"DESCRIBE v_{m}_periodic_report").fetchdf()
        schemas[m] = df["column_name"].tolist()
    assert schemas["a"] == schemas["hk"] == schemas["us"], (
        f"schema 不一致:\nA={schemas['a']}\nHK={schemas['hk']}\nUS={schemas['us']}"
    )


def test_a_specific_fields_populated_in_a_view(store):
    """A 股独有字段在 v_a_periodic_report 上必须有非空值(用比亚迪验证)。"""
    df = store._conn.execute(
        """
        SELECT TOTAL_SHARE, PARENTNETPROFIT, INDUSTRY_NAME, MONETARYFUNDS
        FROM v_a_periodic_report
        WHERE _symbol = '002594.SZ' AND REPORT_DATE = '2024-12-31'
        """
    ).fetchdf()
    if df.empty:
        pytest.skip("002594.SZ 2024-12-31 数据不存在")
    row = df.iloc[0]
    assert row["TOTAL_SHARE"] is not None and row["TOTAL_SHARE"] > 0
    assert row["PARENTNETPROFIT"] is not None and row["PARENTNETPROFIT"] > 0
    assert row["INDUSTRY_NAME"]  # 非空字符串
    assert row["MONETARYFUNDS"] is not None and row["MONETARYFUNDS"] > 0


def test_a_specific_fields_null_in_hk_view(store):
    """A 独有字段在 HK 视图上必须 NULL(用腾讯验证)。"""
    df = store._conn.execute(
        """
        SELECT TOTAL_SHARE, PARENTNETPROFIT, INDUSTRY_NAME, FCFF_BACK
        FROM v_hk_periodic_report
        WHERE _symbol = '00700.HK' AND REPORT_DATE = '2024-12-31'
        """
    ).fetchdf()
    if df.empty:
        pytest.skip("00700.HK 2024-12-31 数据不存在")
    row = df.iloc[0]
    import pandas as pd

    assert pd.isna(row["TOTAL_SHARE"]), "HK TOTAL_SHARE 应为 NULL"
    assert pd.isna(row["PARENTNETPROFIT"]), "HK PARENTNETPROFIT 应为 NULL"
    assert pd.isna(row["FCFF_BACK"]), "HK FCFF_BACK 应为 NULL"
    assert row["INDUSTRY_NAME"] is None, "HK INDUSTRY_NAME 应为 NULL"


def test_hk_monetary_funds_synonym_unified(store):
    """HK 视图的 MONETARYFUNDS 必须从物理 CASH_EQUIVALENTS 派生(同义统一)。"""
    df = store._conn.execute(
        """
        SELECT b.CASH_EQUIVALENTS AS raw_cash, p.MONETARYFUNDS AS biz_mf
        FROM v_hk_balance b
        JOIN v_hk_periodic_report p
          ON p._symbol = b._symbol AND p.REPORT_DATE = b.REPORT_DATE
        WHERE b._symbol = '00700.HK' AND b.REPORT_DATE = '2024-12-31'
        """
    ).fetchdf()
    if df.empty:
        pytest.skip("00700.HK 2024-12-31 balance 数据不存在")
    row = df.iloc[0]
    assert row["raw_cash"] == row["biz_mf"], (
        f"HK MONETARYFUNDS({row['biz_mf']}) ≠ CASH_EQUIVALENTS({row['raw_cash']})"
    )


def test_hk_capex_double_alias(store):
    """HK 视图的 CAPEX 与 CONSTRUCT_LONG_ASSET 必须同值(双别名指向 cashflow.CAPEX)。"""
    df = store._conn.execute(
        """
        SELECT CAPEX, CONSTRUCT_LONG_ASSET
        FROM v_hk_periodic_report
        WHERE _symbol = '00700.HK' AND CAPEX IS NOT NULL
        ORDER BY REPORT_DATE DESC LIMIT 1
        """
    ).fetchdf()
    if df.empty:
        pytest.skip("00700.HK 无 CAPEX 数据")
    row = df.iloc[0]
    assert row["CAPEX"] == row["CONSTRUCT_LONG_ASSET"], (
        f"HK CAPEX({row['CAPEX']}) ≠ CONSTRUCT_LONG_ASSET({row['CONSTRUCT_LONG_ASSET']})"
    )


def test_a_capex_double_alias(store):
    """A 股视图的 CAPEX 与 CONSTRUCT_LONG_ASSET 必须同值(双别名指向 cashflow.CONSTRUCT_LONG_ASSET)。"""
    df = store._conn.execute(
        """
        SELECT CAPEX, CONSTRUCT_LONG_ASSET
        FROM v_a_periodic_report
        WHERE _symbol = '002594.SZ' AND CAPEX IS NOT NULL
        ORDER BY REPORT_DATE DESC LIMIT 1
        """
    ).fetchdf()
    if df.empty:
        pytest.skip("002594.SZ 无 CAPEX 数据")
    row = df.iloc[0]
    assert row["CAPEX"] == row["CONSTRUCT_LONG_ASSET"]


def test_periodic_report_51_cols(store):
    """三市场业务视图都是 51 列(锚定 schema 形状,意外增减触发 review)。
    第 51 列 is_hk_connect:HK 视图来自 v_hk_connect_latest LEFT JOIN,A/US 恒 FALSE。"""
    for m in MARKETS:
        n = len(store._conn.execute(f"DESCRIBE v_{m}_periodic_report").fetchdf())
        assert n == 51, f"v_{m}_periodic_report 应为 51 列,实际 {n}"
