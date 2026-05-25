"""阶段 5 RED:CpaAgent Phase 0 集成测试。

cpa 在 Phase 1 数据包前增加 Phase 0 定性分析:
  - 注入 qualitative_cache 时:Phase 0 运行(命中缓存秒过,未命中走 mock 维度)
  - 不注入(None)时:跳过 Phase 0,行为与改造前一致(向后兼容)
  - Phase 0 静默运行(on_event=None),不向外发 6 个维度的 tool_start/tool_done
  - 但发一个外层 tool_start("phase0_qualitative") + tool_done
  - _meta.json 应记录 phase0_qualitative=done

注意:Phase 0 失败应"软失败"——不阻断后续 Phase 1/3,因为定性参数缺失
不影响 cpa 主流程产出量化报告(只是降级)。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.agents.cpa.agent import CpaAgent
from services.agent.core.qualitative.cache import QualitativeCache
from services.agent.core.qualitative.schema import (
    DimensionReport,
    QualitativeParams,
    QualitativeReport,
)
from services.agent.core.symbol import StockRef


class _FakeStreamLLM:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    async def stream(self, prompt, **kwargs):
        self.calls += 1
        yield self.text


QUANT_REPORT = """# Phase 3.1
<results>
owner_earnings_I=100
final_return_GG=12.5
threshold_II=10
margin_KK=0.5
trap_risk=低
extrapolation_confidence=高
</results>
"""

VALUATION_REPORT = "# 投资分析报告\n\nA"


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


def _make_dim(name: str) -> DimensionReport:
    return DimensionReport(
        name=name, title=f"维度{name[1:]}", narrative=f"{name} ok", evidence=[]
    )


@pytest.fixture
def patched_builder():
    def fake_build(self, ref, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "data_pack_market.md"
        out.write_text(f"# 数据包 {ref.code}\n", encoding="utf-8")
        return out

    with patch(
        "services.agent.agents.cpa.pipeline.phase1_data_pack.builder.DataPackBuilder.build",
        new=fake_build,
    ):
        yield


def _make_agent(tmp_path: Path, sent: list[dict], *, with_cache: bool = True):
    async def sse_send(ev):
        sent.append(ev)

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}
    si = MagicMock()
    si.get_name.return_value = "贵州茅台"

    from services.agent.core.workspace import Workspace

    ws = Workspace(tmp_path / "ws")
    quant_llm = _FakeStreamLLM(QUANT_REPORT)
    val_llm = _FakeStreamLLM(VALUATION_REPORT)

    def factory(phase: str):
        if phase == "phase3_quant":
            return quant_llm
        if phase == "phase3_valuation":
            return val_llm
        return MagicMock()

    qcache = QualitativeCache(tmp_path / "qual") if with_cache else None

    agent = CpaAgent(
        sse_send=sse_send,
        repo=repo,
        workspace=ws,
        stock_index=si,
        llm_factory=factory,
        qualitative_cache=qcache,
        qualitative_params_fallback=_params_full(),
    )
    return agent, ws, qcache


# ===== 测试 =====


async def test_phase0_runs_when_cache_provided(tmp_path, patched_builder):
    """注入 cache 时 Phase 0 运行,_meta 记录,不污染外层 SSE。"""
    sent: list[dict] = []
    agent, ws, qcache = _make_agent(tmp_path, sent)
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    await agent.run("s1", ref)

    # 应有 4 个 tool_start(phase0 + phase1 + phase3_quant + phase3_valuation)
    starts = [e for e in sent if e["type"] == "tool_start"]
    tools = [e["tool"] for e in starts]
    assert "phase0_qualitative" in tools
    assert tools[0] == "phase0_qualitative", "Phase 0 应在 Phase 1 之前"

    # 不应泄漏维度子事件(d1/d2/...)— Phase 0 静默运行
    assert not any(
        e.get("tool", "").startswith("d") and len(e.get("tool", "")) == 2
        for e in starts
    )

    # _meta.json 4 阶段都 done
    d = ws.resolve_dir(ref)
    meta = ws.read_meta(d)
    assert meta["phases"]["phase0_qualitative"]["status"] == "done"
    assert meta["phases"]["phase3_valuation"]["status"] == "done"

    # 定性 cache 应已写入
    assert qcache.get("600519.SH") is not None


async def test_phase0_skipped_when_cache_not_provided(tmp_path, patched_builder):
    """不注入 cache 时跳过 Phase 0,行为与改造前一致。"""
    sent: list[dict] = []
    agent, ws, _ = _make_agent(tmp_path, sent, with_cache=False)
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    await agent.run("s1", ref)

    starts = [e for e in sent if e["type"] == "tool_start"]
    tools = [e["tool"] for e in starts]
    assert "phase0_qualitative" not in tools
    # 仍有原 3 阶段
    assert "phase1_data_pack" in tools
    assert "phase3_valuation" in tools

    d = ws.resolve_dir(ref)
    meta = ws.read_meta(d)
    assert "phase0_qualitative" not in meta.get("phases", {})


async def test_phase0_cache_hit_is_fast_path(tmp_path, patched_builder):
    """缓存命中:Phase 0 不应调维度函数(预置缓存,所有维度函数注入 raise)。"""
    sent: list[dict] = []
    agent, ws, qcache = _make_agent(tmp_path, sent)
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    # 预置缓存
    qcache.put(
        QualitativeReport(
            stock_code="600519.SH",
            stock_name="贵州茅台",
            report_date="unknown",
            dimensions=[_make_dim(f"D{i}") for i in range(1, 7)],
            params=_params_full(),
        )
    )

    # 替换为全 raise 的维度函数 — 命中缓存就不该被调到
    async def _boom(ref, *, store, tavily, llm):
        raise AssertionError("缓存命中时不应调维度函数")

    agent.qualitative_dimension_fns = {f"D{i}": _boom for i in range(1, 7)}

    await agent.run("s1", ref)

    d = ws.resolve_dir(ref)
    meta = ws.read_meta(d)
    assert meta["phases"]["phase0_qualitative"]["status"] == "done"


async def test_phase0_failure_does_not_block_pipeline(tmp_path, patched_builder):
    """Phase 0 抛异常应被 cpa 容忍 — 后续 Phase 1/3 仍执行。"""
    sent: list[dict] = []
    agent, ws, _ = _make_agent(tmp_path, sent)
    ref = StockRef(code="600519.SH", name="贵州茅台", market="A")

    # 注入一个会抛错的 cache(get/put 都抛)
    boom_cache = MagicMock()
    boom_cache.get.side_effect = RuntimeError("cache down")
    boom_cache.put.side_effect = RuntimeError("cache down")
    boom_cache.data_dir = tmp_path / "qual"
    agent.qualitative_cache = boom_cache

    await agent.run("s1", ref)

    types = [e["type"] for e in sent]
    # 最终仍应 done
    assert types[-1] == "done"
    # _meta 中 phase0 标记 failed,phase3_valuation 仍 done
    d = ws.resolve_dir(ref)
    meta = ws.read_meta(d)
    assert meta["phases"]["phase0_qualitative"]["status"] == "failed"
    assert meta["phases"]["phase3_valuation"]["status"] == "done"
