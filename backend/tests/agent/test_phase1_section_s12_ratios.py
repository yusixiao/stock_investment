"""问股期 1 — Task 25:§12 关键比率测试。"""

from unittest.mock import MagicMock

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s12_ratios
from services.agent.core.symbol import StockRef


def test_section_12_ratios_basic():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "ROEJQ": 15.3,
            "ROAJQ": 7.5,
            "GROSSPROFIT_MARGIN": 19.5,
            "NETPROFIT_MARGIN": 4.5,
            "DEBT_ASSET_RATIO": 68.7,
            "CURRENT_RATIO": 1.05,
        },
        {
            "REPORT_DATE": "2024-12-31",
            "ROEJQ": 24.5,
            "ROAJQ": 8.5,
            "GROSSPROFIT_MARGIN": 18.3,
            "NETPROFIT_MARGIN": 5.0,
            "DEBT_ASSET_RATIO": 71.2,
            "CURRENT_RATIO": 0.98,
        },
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s12_ratios.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §12 关键比率" in out
    assert "ROE" in out and "15.30" in out
    assert "毛利率" in out


def test_section_12_empty():
    s = MagicMock()
    s.query_financial_for_section.return_value = []
    out = s12_ratios.build(
        StockRef("X", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "数据缺失" in out
