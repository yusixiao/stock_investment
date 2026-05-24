"""问股期 1 — Task 21:§2 市值/股价测试。"""

from unittest.mock import MagicMock

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s02_market
from services.agent.core.symbol import StockRef


def test_normal_with_price_and_shares():
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    store.query_qfq_kline_for_section.return_value = [
        {"date": "2026-05-23", "close": 250.0}
    ]
    store.query_total_shares_for_section.return_value = 3_000_000_000
    store.query_circulating_shares_for_section.return_value = 1_000_000_000
    out = s02_market.build(
        ref, store=store, stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "## §2 市值/股价" in out
    assert "250.00" in out
    assert "2026-05-23" in out
    # 总股本 30 亿 + 流通 A 股 10 亿
    assert "总股本(股):3,000,000,000" in out
    assert "流通 A 股(股):1,000,000,000" in out
    # 总市值 250 × 30 亿 = 7500 亿 → 750,000 百万
    assert "总市值(百万元):750,000" in out
    # 流通市值 250 × 10 亿 = 2500 亿 → 250,000 百万
    assert "流通市值(百万元):250,000" in out


def test_empty_kline_returns_missing():
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    store.query_qfq_kline_for_section.return_value = []
    out = s02_market.build(
        ref, store=store, stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "## §2 市值/股价" in out
    assert "数据缺失" in out


def test_kline_but_no_shares():
    ref = StockRef(code="00700.HK", name="腾讯控股", market="HK")
    store = MagicMock()
    store.query_qfq_kline_for_section.return_value = [
        {"date": "2026-05-23", "close": 380.5}
    ]
    store.query_total_shares_for_section.return_value = 0
    store.query_circulating_shares_for_section.return_value = 0
    out = s02_market.build(
        ref, store=store, stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "380.50" in out
    assert "总股本:—" in out
    assert "总市值:—" in out
    assert "流通 A 股:—" in out
    assert "流通市值:—" in out


def test_store_exception_falls_back_to_missing():
    ref = StockRef(code="AAPL", name="Apple Inc", market="US")
    store = MagicMock()
    store.query_qfq_kline_for_section.side_effect = RuntimeError("boom")
    out = s02_market.build(
        ref, store=store, stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "数据缺失" in out
