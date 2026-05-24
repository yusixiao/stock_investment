"""问股期 1 — Task 20:DataPackBuilder 骨架测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.builder import DataPackBuilder
from services.agent.symbol import StockRef


def test_builder_produces_file_with_placeholders(tmp_path):
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    store = MagicMock()
    builder = DataPackBuilder(
        store=store,
        stock_index=MagicMock(),
        indicators=MagicMock(),
        include=("s07", "s08", "s10", "s14", "s16"),
    )
    out = builder.build(ref, tmp_path)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "## §7" in text and "WebSearch(期 2 实现)" in text
    assert "## §8" in text
    assert "## §10" in text
    assert "## §14 无风险利率" in text and "2.70" in text
    assert "## §16" in text
    assert "比亚迪" in text and "002594.SZ" in text


def test_unknown_section_keys_skipped(tmp_path):
    ref = StockRef(code="AAPL", name="Apple", market="US")
    builder = DataPackBuilder(
        store=MagicMock(),
        stock_index=MagicMock(),
        indicators=MagicMock(),
        include=("s07", "s14", "s99_nonexistent"),
    )
    out = builder.build(ref, tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "§7" in text and "§14" in text
    assert "s99" not in text


def test_include_order_respected(tmp_path):
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")
    builder = DataPackBuilder(
        store=MagicMock(),
        stock_index=MagicMock(),
        indicators=MagicMock(),
        include=("s14", "s07"),
    )
    out = builder.build(ref, tmp_path)
    text = out.read_text(encoding="utf-8")
    i14 = text.index("§14")
    i07 = text.index("§7")
    assert i14 < i07
