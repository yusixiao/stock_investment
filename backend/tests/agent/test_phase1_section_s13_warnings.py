"""问股期 1 — Task 25:§13 自检 Warnings 测试。"""

from unittest.mock import MagicMock

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s13_warnings
from services.agent.core.symbol import StockRef


def test_section_13_no_warnings_when_healthy():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "DEBT_ASSET_RATIO": 55.0,
            "GOODWILL": 1e8,
            "TOTAL_EQUITY": 1e11,
        }
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s13_warnings.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §13 数据自检 Warnings" in out
    assert "无显著异常" in out


def test_section_13_high_leverage_warning():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "DEBT_ASSET_RATIO": 85.0,
            "GOODWILL": 0,
            "TOTAL_EQUITY": 1e10,
        }
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s13_warnings.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "资产负债率 > 80%" in out
    assert "高杠杆" in out


def test_section_13_goodwill_impairment_warning():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "DEBT_ASSET_RATIO": 50.0,
            "GOODWILL": 5e10,
            "TOTAL_EQUITY": 1e11,
        }
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s13_warnings.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "商誉" in out
    assert "减值风险" in out


def test_section_13_both_warnings_listed():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "DEBT_ASSET_RATIO": 90.0,
            "GOODWILL": 8e10,
            "TOTAL_EQUITY": 1e11,
        }
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s13_warnings.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "高杠杆" in out
    assert "减值风险" in out
    assert out.count("⚠️") >= 2


def test_section_13_no_data_no_crash():
    s = MagicMock()
    s.query_financial_for_section.return_value = []
    out = s13_warnings.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §13 数据自检 Warnings" in out
    assert "无显著异常" in out


def test_section_13_store_raises_no_crash():
    s = MagicMock()
    s.query_financial_for_section.side_effect = RuntimeError("store error")
    out = s13_warnings.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §13 数据自检 Warnings" in out
