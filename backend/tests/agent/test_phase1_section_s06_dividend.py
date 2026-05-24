"""问股期 1 — Task 24:§6 每股股息测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import s06_dividend
from services.agent.symbol import StockRef


def test_section_6_dps_5_years():
    s = MagicMock()
    s.query_dividend_bulk.return_value = [
        {"year": "2025", "dps": 2.05},
        {"year": "2024", "dps": 1.10},
        {"year": "2023", "dps": 0.49},
        {"year": "2022", "dps": 0.11},
        {"year": "2021", "dps": 0.0},
    ]
    out = s06_dividend.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §6" in out
    assert "2.05" in out and "0.49" in out


def test_section_6_empty():
    s = MagicMock()
    s.query_dividend_bulk.return_value = []
    out = s06_dividend.build(
        StockRef("X", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "数据缺失" in out
