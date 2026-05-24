"""问股期 1 — Task 21:§2 市值/股价测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import s02_market
from services.agent.symbol import StockRef


def test_normal_with_price_and_shares():
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    store.query_qfq_kline.return_value = [{"date": "2026-05-23", "close": 250.0}]
    store.query_circulating_shares.return_value = 1_000_000_000
    out = s02_market.build(
        ref, store=store, stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "## §2 市值/股价" in out
    assert "250.00" in out
    assert "2026-05-23" in out
    assert "1,000,000,000" in out
    # 250 * 1e9 = 2.5e11,/1e6 = 250000
    assert "250,000" in out


def test_empty_kline_returns_missing():
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    store.query_qfq_kline.return_value = []
    out = s02_market.build(
        ref, store=store, stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "## §2 市值/股价" in out
    assert "数据缺失" in out


def test_kline_but_no_shares():
    ref = StockRef(code="00700.HK", name="腾讯控股", market="HK")
    store = MagicMock()
    store.query_qfq_kline.return_value = [{"date": "2026-05-23", "close": 380.5}]
    store.query_circulating_shares.return_value = 0
    out = s02_market.build(
        ref, store=store, stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "380.50" in out
    assert "流通股本:—" in out
    assert "流通市值:—" in out


def test_store_exception_falls_back_to_missing():
    ref = StockRef(code="AAPL", name="Apple Inc", market="US")
    store = MagicMock()
    store.query_qfq_kline.side_effect = RuntimeError("boom")
    out = s02_market.build(
        ref, store=store, stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "数据缺失" in out
