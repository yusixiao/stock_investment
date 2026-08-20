"""问股 #6 — current_report_date 真实接入 DuckDB 的回归测试。

覆盖:
1. DuckDBStore.query_latest_report_date 正常返回 / 视图缺失 / 异常 容错
2. CpaAgent Phase 0 调用 store.query_latest_report_date 并把结果传给 run_qualitative
3. BusinessAnalysisAgent 默认 current_report_date 为 None 时回退到 store 查询
4. store 异常时两个 agent 都降级为 None,不抛
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.agents.business_analysis.agent import BusinessAnalysisAgent
from services.agent.agents.cpa.agent import CpaAgent
from services.agent.core.qualitative.cache import QualitativeCache
from services.agent.core.qualitative.schema import (
    DimensionReport,
    QualitativeParams,
    QualitativeReport,
)
from services.agent.core.symbol import StockRef
from backend.tests.fixtures.mini_market import mini_market


# ===== DuckDBStore.query_latest_report_date =====


def test_query_latest_report_date_real_store(mini_market):
    """mini parquet + 真实 DuckDBStore 应返回报告期字符串。"""
    from services.market_data.duckdb_store import DuckDBStore

    s = DuckDBStore()
    try:
        rd = s.query_latest_report_date("002594.SZ")
        assert rd is not None
        assert isinstance(rd, str)
        assert len(rd) == 10 and rd[4] == "-" and rd[7] == "-"
    finally:
        s.close()


def test_query_latest_report_date_view_missing(mini_market):
    """视图不存在 → None,不抛。"""
    from services.market_data.duckdb_store import DuckDBStore

    s = DuckDBStore()
    with patch.object(s, "_view_exists", return_value=False):
        assert s.query_latest_report_date("999999.SZ") is None
    s.close()


def test_query_latest_report_date_db_error(mini_market):
    """SQL 抛异常 → None,不冒泡。"""
    from services.market_data.duckdb_store import DuckDBStore

    s = DuckDBStore()
    fake_conn = MagicMock()
    fake_conn.execute.side_effect = RuntimeError("boom")
    with (
        patch.object(s, "_view_exists", return_value=True),
        patch.object(s, "_conn", fake_conn),
    ):
        assert s.query_latest_report_date("002594.SZ") is None
    s.close()


# ===== CpaAgent 接入 =====


def _params_full() -> QualitativeParams:
    return QualitativeParams(
        capital_intensity="capital-light",
        collection_mode="先款后货",
        moat_type="[占位]",
        moat_flywheel=False,
        moat_rating="强",
        cyclicality="非周期",
        management_rating="合格",
        mda_credibility="高",
        mda_impact="正面",
        holding_structure=False,
    )


@pytest.fixture
def patched_builder():
    def fake_build(self, ref, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "data_pack_market.md"
        out.write_text("# data\n", encoding="utf-8")
        return out

    with patch(
        "services.agent.agents.cpa.pipeline.phase1_data_pack.builder.DataPackBuilder.build",
        new=fake_build,
    ):
        yield


class _FakeStreamLLM:
    def __init__(self, text: str):
        self.text = text

    async def stream(self, prompt, **kwargs):
        yield self.text


QUANT = (
    "<results>\nowner_earnings_I=100\nfinal_return_GG=12.5\nthreshold_II=10\n"
    "margin_KK=0.5\ntrap_risk=低\nextrapolation_confidence=高\n</results>"
)


def _make_cpa_agent(tmp_path: Path, store):
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}
    si = MagicMock()
    si.get_name.return_value = "贵州茅台"

    from services.agent.core.workspace import Workspace

    ws = Workspace(tmp_path / "ws")

    def factory(phase: str):
        if phase == "phase3_quant":
            return _FakeStreamLLM(QUANT)
        if phase == "phase3_valuation":
            return _FakeStreamLLM("# 报告\n")
        return MagicMock()

    qcache = QualitativeCache(tmp_path / "qual")

    agent = CpaAgent(
        sse_send=sse_send,
        repo=repo,
        workspace=ws,
        stock_index=si,
        llm_factory=factory,
        store=store,
        qualitative_cache=qcache,
        qualitative_params_fallback=_params_full(),
    )
    return agent, sent, qcache


async def test_cpa_phase0_passes_latest_report_date_from_store(
    tmp_path, patched_builder
):
    """CpaAgent 应从 store 查最新 REPORT_DATE 并透传给 run_qualitative。"""
    store = MagicMock()
    store.query_latest_report_date.return_value = "2025-03-31"

    agent, sent, qcache = _make_cpa_agent(tmp_path, store)
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    captured = {}

    async def spy(ref, **kwargs):
        captured["current_report_date"] = kwargs.get("current_report_date")
        # 返回最小可用 report 让 cpa 后续流程不崩
        return QualitativeReport(
            stock_code=ref.code,
            stock_name=ref.name,
            report_date=kwargs.get("current_report_date") or "unknown",
            dimensions=[
                DimensionReport(
                    name=f"D{i}", title=f"维度{i}", narrative="ok", evidence=[]
                )
                for i in range(1, 7)
            ],
            params=_params_full(),
        )

    with patch("services.agent.agents.cpa.agent.run_qualitative", side_effect=spy):
        await agent.run("s1", ref)

    store.query_latest_report_date.assert_called_once_with("600519.SH")
    assert captured["current_report_date"] == "2025-03-31"


async def test_cpa_phase0_store_error_degrades_to_none(tmp_path, patched_builder):
    """store.query_latest_report_date 抛错时,Phase 0 仍跑(传 None)。"""
    store = MagicMock()
    store.query_latest_report_date.side_effect = RuntimeError("db down")

    agent, sent, _ = _make_cpa_agent(tmp_path, store)
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    captured = {}

    async def spy(ref, **kwargs):
        captured["current_report_date"] = kwargs.get("current_report_date")
        return QualitativeReport(
            stock_code=ref.code,
            stock_name=ref.name,
            report_date="unknown",
            dimensions=[
                DimensionReport(
                    name=f"D{i}", title=f"维度{i}", narrative="ok", evidence=[]
                )
                for i in range(1, 7)
            ],
            params=_params_full(),
        )

    with patch("services.agent.agents.cpa.agent.run_qualitative", side_effect=spy):
        await agent.run("s1", ref)

    assert captured["current_report_date"] is None
    # 最终仍正常完成
    assert sent[-1]["type"] == "done"


# ===== BusinessAnalysisAgent 接入 =====


def _make_ba_agent(tmp_path: Path, *, store, current_report_date=None):
    sent: list[dict] = []

    async def sse_send(ev):
        sent.append(ev)

    repo = MagicMock()
    si = MagicMock()
    si.get_name.return_value = "贵州茅台"
    cache = QualitativeCache(tmp_path / "qual")

    agent = BusinessAnalysisAgent(
        sse_send=sse_send,
        repo=repo,
        stock_index=si,
        qualitative_cache=cache,
        params_fallback=_params_full(),
        current_report_date=current_report_date,
        store=store,
    )
    return agent, sent


async def test_ba_agent_falls_back_to_store_when_report_date_none(tmp_path):
    """BA agent 未显式传 current_report_date 时,应从 store 查。"""
    store = MagicMock()
    store.query_latest_report_date.return_value = "2025-06-30"
    agent, sent = _make_ba_agent(tmp_path, store=store)
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    captured = {}

    async def spy(ref, **kwargs):
        captured["current_report_date"] = kwargs.get("current_report_date")
        return QualitativeReport(
            stock_code=ref.code,
            stock_name=ref.name,
            report_date="2025-06-30",
            dimensions=[
                DimensionReport(
                    name=f"D{i}", title=f"维度{i}", narrative="ok", evidence=[]
                )
                for i in range(1, 7)
            ],
            params=_params_full(),
        )

    with patch(
        "services.agent.agents.business_analysis.agent.run_qualitative", side_effect=spy
    ):
        await agent.run("sess", ref)

    store.query_latest_report_date.assert_called_once_with("600519.SH")
    assert captured["current_report_date"] == "2025-06-30"


async def test_ba_agent_explicit_report_date_skips_store_query(tmp_path):
    """显式传入 current_report_date 时,不应再查 store(节省一次 IO)。"""
    store = MagicMock()
    store.query_latest_report_date.return_value = "should_not_be_used"
    agent, sent = _make_ba_agent(
        tmp_path, store=store, current_report_date="2024-12-31"
    )
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    captured = {}

    async def spy(ref, **kwargs):
        captured["current_report_date"] = kwargs.get("current_report_date")
        return QualitativeReport(
            stock_code=ref.code,
            stock_name=ref.name,
            report_date="2024-12-31",
            dimensions=[
                DimensionReport(
                    name=f"D{i}", title=f"维度{i}", narrative="ok", evidence=[]
                )
                for i in range(1, 7)
            ],
            params=_params_full(),
        )

    with patch(
        "services.agent.agents.business_analysis.agent.run_qualitative", side_effect=spy
    ):
        await agent.run("sess", ref)

    store.query_latest_report_date.assert_not_called()
    assert captured["current_report_date"] == "2024-12-31"


async def test_ba_agent_store_error_degrades_to_none(tmp_path):
    """store 抛错时降级为 None,不冒泡。"""
    store = MagicMock()
    store.query_latest_report_date.side_effect = RuntimeError("db down")
    agent, sent = _make_ba_agent(tmp_path, store=store)
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    captured = {}

    async def spy(ref, **kwargs):
        captured["current_report_date"] = kwargs.get("current_report_date")
        return QualitativeReport(
            stock_code=ref.code,
            stock_name=ref.name,
            report_date="unknown",
            dimensions=[
                DimensionReport(
                    name=f"D{i}", title=f"维度{i}", narrative="ok", evidence=[]
                )
                for i in range(1, 7)
            ],
            params=_params_full(),
        )

    with patch(
        "services.agent.agents.business_analysis.agent.run_qualitative", side_effect=spy
    ):
        await agent.run("sess", ref)

    assert captured["current_report_date"] is None
    assert sent[-1]["type"] == "done"
