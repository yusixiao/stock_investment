"""问股期 1 — Task 24:§15 行业估值测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import s15_industry_valuation
from services.agent.symbol import StockRef


def test_section_15_industry_median():
    s = MagicMock()
    s.query_industry_valuation_summary.return_value = {
        "industry": "汽车整车",
        "pe_median": 25.3,
        "pb_median": 3.1,
        "sample_size": 42,
    }
    out = s15_industry_valuation.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §15 行业平均估值" in out
    assert "25.3" in out and "3.1" in out


def test_section_15_no_industry_data():
    s = MagicMock()
    s.query_industry_valuation_summary.return_value = None
    out = s15_industry_valuation.build(
        StockRef("X", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "—" in out or "数据缺失" in out
