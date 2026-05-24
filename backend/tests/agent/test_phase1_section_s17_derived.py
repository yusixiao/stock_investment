"""问股期 1 — Task 25:§17 衍生指标测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import s17_derived
from services.agent.symbol import StockRef


def test_section_17_macd_ma():
    ind = MagicMock()
    ind.get_indicator_snapshot.return_value = {
        "MA5": 268.0,
        "MA10": 265.0,
        "MA20": 260.5,
        "MA60": 255.0,
        "MACD_DIF": 0.5,
        "MACD_DEA": 0.2,
        "MACD_BAR": 0.6,
        "PE_PCT_5Y": 0.42,
        "PB_PCT_5Y": 0.38,
    }
    out = s17_derived.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=MagicMock(),
        stock_index=MagicMock(),
        indicators=ind,
    )
    assert "## §17 衍生指标" in out
    assert "MA5" in out and "268.00" in out
    assert "MACD" in out
    assert "PE 历史分位" in out and "42" in out


def test_section_17_no_snapshot_no_crash():
    ind = MagicMock()
    ind.get_indicator_snapshot.return_value = None
    out = s17_derived.build(
        StockRef("X", "x", "A"),
        store=MagicMock(),
        stock_index=MagicMock(),
        indicators=ind,
    )
    assert "## §17 衍生指标" in out
    assert "—" in out


def test_section_17_indicators_lacks_method():
    class _NoIndicators:
        pass

    out = s17_derived.build(
        StockRef("X", "x", "A"),
        store=MagicMock(),
        stock_index=MagicMock(),
        indicators=_NoIndicators(),
    )
    assert "## §17 衍生指标" in out
