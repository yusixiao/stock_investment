"""问股期 1 — Task 21:§1 基础信息测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import s01_basic
from services.agent.symbol import StockRef


def test_a_share_section1():
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    si = MagicMock()
    si.get_industry.return_value = "汽车整车"
    out = s01_basic.build(
        ref, store=MagicMock(), stock_index=si, indicators=MagicMock()
    )
    assert "## §1 基础信息" in out
    assert "002594.SZ" in out and "比亚迪" in out
    assert "CNY" in out
    assert "A 股" in out
    assert "汽车整车" in out


def test_hk_share_currency():
    ref = StockRef(code="00700.HK", name="腾讯控股", market="HK")
    out = s01_basic.build(
        ref, store=MagicMock(), stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "HKD" in out
    assert "港股" in out


def test_us_currency():
    ref = StockRef(code="AAPL", name="Apple Inc", market="US")
    out = s01_basic.build(
        ref, store=MagicMock(), stock_index=MagicMock(), indicators=MagicMock()
    )
    assert "USD" in out
    assert "美股" in out


def test_industry_missing_falls_back_to_dash():
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")
    si = MagicMock(spec=[])  # 无 get_industry 方法
    out = s01_basic.build(
        ref, store=MagicMock(), stock_index=si, indicators=MagicMock()
    )
    assert "—" in out
