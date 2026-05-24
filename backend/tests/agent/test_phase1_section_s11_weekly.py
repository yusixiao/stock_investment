"""问股期 1 — Task 24:§11 周线测试。"""

from unittest.mock import MagicMock

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s11_weekly_kline
from services.agent.core.symbol import StockRef


def test_section_11_basic():
    rows = [
        {
            "date": f"2026-{m:02d}-01",
            "close": 100 + m,
            "high": 105 + m,
            "low": 95 + m,
            "volume": 1e6,
        }
        for m in range(1, 6)
    ]
    s = MagicMock()
    s.query_qfq_kline_for_section.return_value = rows
    out = s11_weekly_kline.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §11 历史价格" in out
    assert "周线" in out
    # 区间涨跌幅 (105/101-1)*100 = 3.96%
    assert "+4.0%" in out or "+3.9%" in out


def test_section_11_empty():
    s = MagicMock()
    s.query_qfq_kline_for_section.return_value = []
    out = s11_weekly_kline.build(
        StockRef("X", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "数据缺失" in out
