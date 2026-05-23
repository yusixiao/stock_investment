import pytest

from services.agent.symbol import StockRef
from services.agent.workspace import Workspace


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(root=tmp_path / "agent_runs")


def test_resolve_dir(ws):
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    d = ws.resolve_dir(ref)
    assert d.name == "002594.SZ_比亚迪"
    assert d.parent == ws.root


def test_ensure_creates_dir(ws):
    ref = StockRef(code="00700.HK", name="腾讯控股", market="HK")
    d = ws.ensure(ref)
    assert d.is_dir()


def test_meta_roundtrip(ws):
    ref = StockRef(code="AAPL", name="Apple Inc", market="US")
    d = ws.ensure(ref)
    meta = {"stock_code": "AAPL", "company": "Apple Inc", "phases": {}}
    ws.write_meta(d, meta)
    loaded = ws.read_meta(d)
    assert loaded == meta


def test_phase_status_helpers(ws):
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")
    d = ws.ensure(ref)
    ws.mark_phase(d, "phase1_data_pack", status="done", duration=1.8)
    meta = ws.read_meta(d)
    assert meta["phases"]["phase1_data_pack"] == {"status": "done", "duration": 1.8}
    assert ws.phase_status(d, "phase1_data_pack") == "done"
    assert ws.phase_status(d, "phase3_quantitative") is None


def test_mark_phase_with_reason(ws):
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")
    d = ws.ensure(ref)
    ws.mark_phase(d, "phase2_llm", status="failed", reason="timeout")
    meta = ws.read_meta(d)
    assert meta["phases"]["phase2_llm"] == {"status": "failed", "reason": "timeout"}


def test_artifact_url_path(ws):
    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    d = ws.ensure(ref)
    p = d / "比亚迪_002594.SZ_分析报告.md"
    p.write_text("# r", encoding="utf-8")
    rel = ws.relpath_for_artifact(d, p)
    assert rel == "002594.SZ_比亚迪/比亚迪_002594.SZ_分析报告.md"


def test_sanitize_strips_unsafe_chars(ws):
    ref = StockRef(code="AAPL", name="Apple/Inc:", market="US")
    d = ws.resolve_dir(ref)
    assert "/" not in d.name and ":" not in d.name


def test_read_meta_missing_returns_empty(ws):
    ref = StockRef(code="AAPL", name="Apple", market="US")
    d = ws.ensure(ref)
    assert ws.read_meta(d) == {}
