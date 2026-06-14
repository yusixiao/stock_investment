"""query_periodic_report_bulk Phase 2 验收测试。

锚定:
  1. 4 个 fin_type 都能拿到对应列子集
  2. HK 股的 MONETARYFUNDS / CONSTRUCT_LONG_ASSET / PARENT_NETPROFIT 同义统一生效
     (这是 4960397f HK 0 交易的根因修复)
  3. A 独有字段在 HK 上 NULL fill,strategies 容错(_safe_float)
"""

import pandas as pd
import pytest

from config import MARKET_DIR
from services.market_data.duckdb_store import DuckDBStore


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


@pytest.mark.parametrize("market", ["A", "HK", "US"])
@pytest.mark.parametrize("fin_type", ["indicator", "income", "balance", "cashflow"])
def test_periodic_report_bulk_returns_data(store, market, fin_type):
    """三市场 × 4 fin_type 都能返回非空字典 + 列子集正确。"""
    out = store.query_periodic_report_bulk(market, symbols=None, fin_type=fin_type)
    assert isinstance(out, dict)
    assert len(out) > 0, f"{market}/{fin_type} 返回空字典"
    # 抽样验证列名
    sample = next(iter(out.values()))
    expected_cols = set(["REPORT_DATE"] + DuckDBStore._PERIODIC_COLS[fin_type])
    actual_cols = set(sample.columns)
    assert expected_cols == actual_cols, (
        f"{market}/{fin_type} 列不匹配:\n"
        f"  expected: {expected_cols}\n  actual: {actual_cols}"
    )


def test_periodic_report_bulk_unknown_fin_type(store):
    """非法 fin_type 返回空字典,不抛异常。"""
    out = store.query_periodic_report_bulk("A", None, fin_type="bogus")
    assert out == {}


def test_hk_synonym_unification_in_bulk(store):
    """HK 00700.HK 通过 bulk 接口必须拿到同义统一后的字段(根因验证)。"""
    bal = store.query_periodic_report_bulk("HK", ["00700.HK"], fin_type="balance").get(
        "00700.HK"
    )
    cf = store.query_periodic_report_bulk("HK", ["00700.HK"], fin_type="cashflow").get(
        "00700.HK"
    )
    inc = store.query_periodic_report_bulk("HK", ["00700.HK"], fin_type="income").get(
        "00700.HK"
    )

    if bal is None or bal.empty:
        pytest.skip("HK 00700.HK balance 数据不存在")

    # MONETARYFUNDS:HK 物理表只有 CASH_EQUIVALENTS,业务视图同义统一
    assert bal["MONETARYFUNDS"].notna().any(), "HK MONETARYFUNDS 全 NULL,同义统一失效"
    assert (bal["MONETARYFUNDS"] > 0).any()

    # CONSTRUCT_LONG_ASSET:HK 物理表只有 CAPEX,业务视图双别名
    assert cf["CONSTRUCT_LONG_ASSET"].notna().any(), (
        "HK CONSTRUCT_LONG_ASSET 全 NULL,双别名失效(strategies 旧引用会断)"
    )

    # PARENT_NETPROFIT:三市场共有,strategies 应当迁到这里替代 PARENTNETPROFIT
    assert inc["PARENT_NETPROFIT"].notna().any()


def test_hk_a_only_fields_null_fill(store):
    """HK 上的 A 独有字段必须 NULL fill,但列存在(strategies _safe_float 容错)。"""
    fin = store.query_periodic_report_bulk(
        "HK", ["00700.HK"], fin_type="indicator"
    ).get("00700.HK")
    if fin is None or fin.empty:
        pytest.skip("HK 00700.HK indicator 数据不存在")

    # 列必须存在(否则 strategies row.get('PARENTNETPROFIT') 会拿不到 None)
    assert "PARENTNETPROFIT" in fin.columns
    assert "TOTAL_SHARE" in fin.columns
    assert "FCFF_BACK" in fin.columns
    # 值应全 NULL
    assert fin["PARENTNETPROFIT"].isna().all()
    assert fin["TOTAL_SHARE"].isna().all()
    assert fin["FCFF_BACK"].isna().all()


def test_a_baseline_unchanged(store):
    """A 股回归基线:002594.SZ balance 数据 = raw view 同源。"""
    biz = store.query_periodic_report_bulk("A", ["002594.SZ"], fin_type="balance").get(
        "002594.SZ"
    )
    raw_df = store._conn.execute(
        "SELECT REPORT_DATE, MONETARYFUNDS, GOODWILL, TOTAL_ASSETS "
        "FROM v_a_balance WHERE _symbol = '002594.SZ' ORDER BY REPORT_DATE"
    ).fetchdf()

    assert biz is not None and not biz.empty
    # 报告期对齐(允许业务视图行数 = indicator 主表,可能 ≥ raw balance)
    common_dates = set(biz["REPORT_DATE"]) & set(raw_df["REPORT_DATE"])
    assert len(common_dates) >= 50, "A 股 balance 报告期重叠应 ≥ 50"

    # 抽 1 期对比 MONETARYFUNDS 数值一致
    sample_date = sorted(common_dates)[-1]
    biz_val = biz[biz["REPORT_DATE"] == sample_date]["MONETARYFUNDS"].iloc[0]
    raw_val = raw_df[raw_df["REPORT_DATE"] == sample_date]["MONETARYFUNDS"].iloc[0]
    assert biz_val == raw_val, (
        f"A 股 002594.SZ {sample_date} MONETARYFUNDS 业务视图({biz_val}) "
        f"≠ raw({raw_val})"
    )
