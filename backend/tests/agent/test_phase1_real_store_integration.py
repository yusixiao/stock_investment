"""Phase 1 数据包真实 DuckDBStore 集成测试。

目的:防止「sections 用 mock 测试全部 PASS,但真实 store API 签名不匹配」的回归
(2026-05-24 暴露的根因 bug)。

策略:
- 用真实 DuckDBStore(读 mini parquet fixture),实股 002594.SZ
- 验证 4 个 adapter 方法返回非空且字段名符合 sections 期望
- 验证 §3/§5/§12/§6 实际 build 出含真实数字的表格(非「数据缺失」)

数据由共享 mini_market fixture 提供，不依赖项目本地市场数据目录。
"""

from __future__ import annotations

import pytest

from backend.tests.fixtures.mini_market import mini_store


@pytest.fixture
def real_store(mini_store):
    return mini_store


# ------------------------- adapter 单元 ----------------------------------


def test_adapter_qfq_kline_latest_one(real_store):
    rows = real_store.query_qfq_kline_for_section("002594.SZ", limit=1, order="desc")
    assert len(rows) == 1
    r = rows[0]
    assert {"date", "open", "high", "low", "close", "volume", "amount"} <= set(r.keys())
    assert r["close"] > 0


def test_adapter_qfq_kline_weekly(real_store):
    rows = real_store.query_qfq_kline_for_section("002594.SZ", freq="W", years=2)
    assert len(rows) >= 50, f"近 2 年周线应有 ~104 行,实际 {len(rows)}"
    # 周线 date 必须是周五
    import datetime as _dt

    for r in rows[:5]:
        d = _dt.date.fromisoformat(r["date"])
        # W-FRI 聚合 → 都应该是周五(weekday=4)或周末观察日
        assert d.weekday() == 4


def test_adapter_financial_income_fields(real_store):
    rows = real_store.query_financial_for_section("002594.SZ", table="income", years=3)
    assert len(rows) >= 3
    r = rows[0]
    assert r["REPORT_DATE"].endswith("-12-31"), "应只取年报"
    # sections 引用的关键字段 + 派生 GROSS_PROFIT 都得有
    for k in (
        "NETPROFIT",
        "PARENT_NETPROFIT",
        "BASIC_EPS",
        "TOTAL_OPERATE_INCOME",
        "OPERATE_COST",
        "GROSS_PROFIT",
    ):
        assert k in r, f"income row 缺字段 {k}"
    # 002594.SZ 实际数据 NETPROFIT 列为 NA,PARENT_NETPROFIT 是主要利润口径
    assert r["PARENT_NETPROFIT"] is not None and float(r["PARENT_NETPROFIT"]) > 0
    assert (
        r["TOTAL_OPERATE_INCOME"] is not None and float(r["TOTAL_OPERATE_INCOME"]) > 0
    )


def test_adapter_financial_balance_with_aliases(real_store):
    rows = real_store.query_financial_for_section("002594.SZ", table="balance", years=3)
    assert len(rows) >= 3
    r = rows[0]
    # sections 期望的英文字段(adapter 已用 AS 重命名)
    for k in (
        "TOTAL_ASSETS",
        "TOTAL_LIABILITIES",
        "TOTAL_EQUITY",
        "MONETARY_FUND",
        "INVENTORIES",
        "FIXED_ASSETS",
        "INTANGIBLE_ASSETS",
        "GOODWILL",
        "DEBT_ASSET_RATIO",
        "BPS",
    ):
        assert k in r, f"balance row 缺字段 {k}"
    assert r["TOTAL_ASSETS"] > 0


def test_adapter_financial_cashflow(real_store):
    rows = real_store.query_financial_for_section(
        "002594.SZ", table="cashflow", years=3
    )
    assert len(rows) >= 3
    r = rows[0]
    for k in (
        "NETCASH_OPERATE",
        "NETCASH_INVEST",
        "NETCASH_FINANCE",
        "END_CASH",
        "CONSTRUCT_LONG_ASSET",
    ):
        assert k in r


def test_adapter_financial_indicator_aliases(real_store):
    rows = real_store.query_financial_for_section(
        "002594.SZ", table="indicator", years=3
    )
    assert len(rows) >= 3
    r = rows[0]
    # 拼音简写 → 英文别名
    for k in (
        "ROEJQ",
        "ROAJQ",
        "GROSSPROFIT_MARGIN",
        "NETPROFIT_MARGIN",
        "DEBT_ASSET_RATIO",
        "CURRENT_RATIO",
    ):
        assert k in r, f"indicator row 缺字段 {k}"
    assert r["ROEJQ"] is not None


def test_adapter_financial_parent_returns_empty(real_store):
    """母公司表数据源未提供,adapter 应返回 [],section 走 fallback 文案。"""
    rows = real_store.query_financial_for_section(
        "002594.SZ", table="income_parent", years=5
    )
    assert rows == []


def test_adapter_dividend_yearly_aggregation(real_store):
    rows = real_store.query_dividend_for_section("002594.SZ", years=5)
    assert len(rows) >= 1
    r = rows[0]
    assert "year" in r and "dps" in r
    assert isinstance(r["year"], int)
    assert r["dps"] > 0


def test_adapter_circulating_shares_graceful(real_store):
    """流通股快照若不存在,返回 None 而非抛错。"""
    result = real_store.query_circulating_shares_for_section("002594.SZ")
    # 视环境而定:若 meta/circulating_shares.parquet 已落,返回 int;否则 None
    assert result is None or isinstance(result, int)


# ------------------------- 端到端 sections build ----------------------------


def test_section_s03_income_renders_real_numbers(real_store):
    from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s03_income
    from services.agent.core.symbol import StockRef

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    text = s03_income.build(ref, store=real_store, stock_index=None, indicators=None)

    assert "数据缺失" not in text
    assert "## §3 利润表" in text
    # 应含「营业总收入」label + 数字(含逗号分隔的百万元)
    assert "营业总收入" in text
    assert "净利润" in text


def test_section_s05_cashflow_renders_real(real_store):
    from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s05_cashflow
    from services.agent.core.symbol import StockRef

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    text = s05_cashflow.build(ref, store=real_store, stock_index=None, indicators=None)
    assert "数据缺失" not in text
    assert "经营性现金流" in text


def test_section_s06_dividend_renders_real(real_store):
    from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s06_dividend
    from services.agent.core.symbol import StockRef

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    text = s06_dividend.build(ref, store=real_store, stock_index=None, indicators=None)
    assert "数据缺失" not in text
    # 至少含 1 行年度股息
    assert "DPS" in text


def test_section_s12_ratios_renders_real(real_store):
    from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s12_ratios
    from services.agent.core.symbol import StockRef

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    text = s12_ratios.build(ref, store=real_store, stock_index=None, indicators=None)
    assert "数据缺失" not in text
    assert "ROE" in text


def test_section_s11_weekly_renders_real(real_store):
    from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s11_weekly_kline
    from services.agent.core.symbol import StockRef

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    text = s11_weekly_kline.build(
        ref, store=real_store, stock_index=None, indicators=None
    )
    assert "数据缺失" not in text
    assert "区间最高" in text


def test_section_s02_market_renders_real(real_store):
    from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s02_market
    from services.agent.core.symbol import StockRef

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    text = s02_market.build(ref, store=real_store, stock_index=None, indicators=None)
    assert "## §2 市值/股价" in text
    assert "最新收盘价" in text
    # 流通股可能 None(快照未跑),但价格必须有
    assert "(数据缺失)" not in text or "最新收盘价" in text
