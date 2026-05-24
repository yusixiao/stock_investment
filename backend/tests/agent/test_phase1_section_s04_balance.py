"""问股期 1 — Task 22:§4 资产负债表测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import s04_balance
from services.agent.symbol import StockRef


def test_section_4_basic():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "TOTAL_ASSETS": 8.0e11,
            "TOTAL_LIABILITIES": 5.5e11,
            "TOTAL_EQUITY": 2.5e11,
            "TOTAL_CURRENT_ASSETS": 3.0e11,
            "TOTAL_CURRENT_LIAB": 3.0e11,
            "MONETARY_FUND": 6.0e10,
            "INVENTORIES": 4.0e10,
            "FIXED_ASSETS": 1.5e11,
            "INTANGIBLE_ASSETS": 2.0e10,
            "GOODWILL": 5.0e9,
            "BPS": 85.5,
        }
    ]
    s = MagicMock()
    s.query_financial.return_value = rows
    out = s04_balance.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §4 资产负债表" in out
    assert "总资产" in out and "总负债" in out and "股东权益" in out
    assert "800,000" in out  # 8e11/1e6
    assert "85.50" in out  # BPS


def test_section_4_empty_emits_warning():
    s = MagicMock()
    s.query_financial.return_value = []
    out = s04_balance.build(
        StockRef("X", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "数据缺失" in out
