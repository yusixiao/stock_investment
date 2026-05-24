"""问股期 1 — Task 22:§5 现金流量表测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import s05_cashflow
from services.agent.symbol import StockRef


def test_section_5_basic():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "NETCASH_OPERATE": 8.0e10,
            "NETCASH_INVEST": -7.0e10,
            "NETCASH_FINANCE": -1.0e10,
            "END_CASH": 7.0e10,
            "DEPRECIATION_FA": 3.0e10,
            "CONSTRUCT_LONG_ASSET": 5.0e10,
        }
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s05_cashflow.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §5 现金流量表" in out
    assert "经营性现金流" in out
    assert "80,000" in out  # 8e10/1e6


def test_section_5_empty_emits_warning():
    s = MagicMock()
    s.query_financial_for_section.return_value = []
    out = s05_cashflow.build(
        StockRef("X", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "数据缺失" in out
