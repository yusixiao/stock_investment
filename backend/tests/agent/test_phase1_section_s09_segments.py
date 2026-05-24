"""问股期 1 — Task 25:§9 主营拆分测试。"""

from unittest.mock import MagicMock

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s09_segments
from services.agent.core.symbol import StockRef


def test_section_09_segments_with_data():
    segs = [
        {"segment": "汽车及相关产品", "revenue_pct": 78.5, "gross_margin": 22.3},
        {"segment": "手机部件、组装及其他", "revenue_pct": 18.2, "gross_margin": 8.6},
        {"segment": "二次充电电池", "revenue_pct": 3.3, "gross_margin": 16.5},
    ]
    s = MagicMock()
    s.query_business_segments.return_value = segs
    out = s09_segments.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §9 主营拆分" in out
    assert "汽车及相关产品" in out
    assert "78.5" in out
    assert "22.3" in out
    assert "营收占比" in out and "毛利率" in out


def test_section_09_segments_empty_returns_placeholder():
    s = MagicMock()
    s.query_business_segments.return_value = []
    out = s09_segments.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §9 主营拆分" in out
    assert "暂未接入" in out


def test_section_09_segments_store_lacks_method_no_crash():
    class _NoMethodStore:
        pass

    out = s09_segments.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=_NoMethodStore(),
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §9 主营拆分" in out
    assert "暂未接入" in out


def test_section_09_segments_store_raises_no_crash():
    s = MagicMock()
    s.query_business_segments.side_effect = RuntimeError("duckdb error")
    out = s09_segments.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §9 主营拆分" in out
