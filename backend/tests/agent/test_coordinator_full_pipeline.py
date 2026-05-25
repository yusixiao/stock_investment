"""问股期 1 — Task 31:Coordinator 完整流水线编排测试。

full_pipeline 在识别到股票码时触发,串接:
  1) Phase 1 数据包(DataPackBuilder)
  2) Phase 3.1 量化(run_phase3_quant)
  3) Phase 3.2 估值与报告(run_phase3_valuation)

每阶段前后发 tool_start / tool_done;LLM 流式片段发 generating;
最终 done 携带报告 artifacts。任一阶段失败发 error 后 return。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.coordinator import Coordinator
from services.agent.core.symbol import StockRef


class _FakeStreamLLM:
    """Fake LLM:支持 stream(prompt) -> async iterator of str。"""

    def __init__(self, text: str, chunks: int = 3):
        self.text = text
        self.chunks = chunks
        self.calls = 0

    async def stream(self, prompt, **kwargs):
        self.calls += 1
        size = max(1, len(self.text) // self.chunks)
        for i in range(0, len(self.text), size):
            yield self.text[i : i + size]


QUANT_REPORT = """# Phase 3.1 量化
<results>
owner_earnings_I=100
final_return_GG=12.5
threshold_II=10
margin_KK=0.5
trap_risk=低
extrapolation_confidence=高
</results>
"""

VALUATION_REPORT = "# 投资分析报告\n\n## 综合评级\nA\n"


def _make_coord(tmp_path: Path, *, quant_llm, valuation_llm, sent: list[dict]):
    async def sse_send(ev):
        sent.append(ev)

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}

    si = MagicMock()
    si.get_name.return_value = "比亚迪"

    from services.agent.core.workspace import Workspace

    ws = Workspace(tmp_path)

    def factory(phase: str):
        if phase == "phase3_quant":
            return quant_llm
        if phase == "phase3_valuation":
            return valuation_llm
        return MagicMock()

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=ws,
        stock_index=si,
        llm_factory=factory,
        qualitative_dir=tmp_path / "qual",
    )
    return coord, ws


@pytest.fixture
def patched_builder():
    """Patch DataPackBuilder 的 build 方法,避免依赖真实 store/indicators。"""

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


async def test_full_pipeline_happy_path(tmp_path, patched_builder):
    sent: list[dict] = []
    quant_llm = _FakeStreamLLM(QUANT_REPORT)
    val_llm = _FakeStreamLLM(VALUATION_REPORT)
    coord, ws = _make_coord(
        tmp_path, quant_llm=quant_llm, valuation_llm=val_llm, sent=sent
    )

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    await coord.run(session_id="s1", message=ref.code, context=None)

    types = [e["type"] for e in sent]
    # Phase 5 起 cpa 含 4 阶段:phase0_qualitative + phase1 + phase3_quant + phase3_valuation
    assert types.count("tool_start") == 4
    assert types.count("tool_done") == 4
    assert types[-1] == "done"
    assert any(e["type"] == "generating" for e in sent)

    # 各阶段 LLM 都被调过一次
    assert quant_llm.calls == 1
    assert val_llm.calls == 1

    # 报告写盘
    d = ws.resolve_dir(ref)
    assert (d / "data_pack_market.md").exists()
    assert (d / "phase3_quantitative.md").exists()
    reports = list(d.glob("*_分析报告.md"))
    assert len(reports) == 1

    # done 事件 artifacts 列表里包含报告路径
    done_ev = sent[-1]
    artifacts = done_ev["artifacts"]
    assert any(reports[0].name in str(a) for a in artifacts)

    # _meta.json 三阶段都为 done
    meta = ws.read_meta(d)
    phases = meta["phases"]
    assert phases["phase1_data_pack"]["status"] == "done"
    assert phases["phase3_quant"]["status"] == "done"
    assert phases["phase3_valuation"]["status"] == "done"


async def test_full_pipeline_phase3_quant_failure_emits_error(
    tmp_path, patched_builder
):
    """Phase 3.1 失败时应发 error 事件并停止后续阶段。"""
    sent: list[dict] = []

    class _Boom:
        async def stream(self, prompt, **kwargs):
            raise RuntimeError("LLM down")
            yield  # pragma: no cover

    val_llm = _FakeStreamLLM(VALUATION_REPORT)
    coord, ws = _make_coord(
        tmp_path, quant_llm=_Boom(), valuation_llm=val_llm, sent=sent
    )

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    await coord.run(session_id="s1", message=ref.code, context=None)

    types = [e["type"] for e in sent]
    assert "error" in types
    err = next(e for e in sent if e["type"] == "error")
    assert err.get("phase") == "phase3_quant"
    # 估值阶段不应被执行
    assert val_llm.calls == 0
    # data_pack_market 仍写入,但 phase3_quant 标记为 failed
    d = ws.resolve_dir(ref)
    meta = ws.read_meta(d)
    assert meta["phases"]["phase1_data_pack"]["status"] == "done"
    assert meta["phases"]["phase3_quant"]["status"] == "failed"


async def test_full_pipeline_persists_assistant_message_with_artifacts(
    tmp_path, patched_builder
):
    """完整流水线完成后应把助手消息(含报告 artifacts)写入 session repo,
    否则用户切回历史会话时只剩用户消息,丢失报告卡片。"""
    sent: list[dict] = []
    quant_llm = _FakeStreamLLM(QUANT_REPORT)
    val_llm = _FakeStreamLLM(VALUATION_REPORT)
    coord, ws = _make_coord(
        tmp_path, quant_llm=quant_llm, valuation_llm=val_llm, sent=sent
    )

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    await coord.run(session_id="s1", message=ref.code, context=None)

    # 必须调用 append_message 写助手消息
    repo = coord.repo
    appended_assistant = [
        c
        for c in repo.append_message.call_args_list
        if c.kwargs.get("role") == "assistant"
    ]
    assert appended_assistant, "完整流水线结束后必须持久化助手消息"

    call = appended_assistant[-1]
    # session_id 必须是当前会话
    assert call.kwargs.get("session_id") == "s1" or call.args[0] == "s1"
    # content 应是最终报告文本(VALUATION_REPORT 的内容)
    content = call.kwargs.get("content", "")
    assert "投资分析报告" in content
    # artifacts 必须包含报告路径
    artifacts = call.kwargs.get("artifacts") or []
    assert artifacts, "助手消息必须带 artifacts"
    reports = list(ws.resolve_dir(ref).glob("*_分析报告.md"))
    assert any(reports[0].name in str(a) for a in artifacts)


async def test_full_pipeline_session_output_dir_persisted(tmp_path, patched_builder):
    """session 应被更新 output_dir 以便后续 qa_followup 命中。"""
    sent: list[dict] = []
    quant_llm = _FakeStreamLLM(QUANT_REPORT)
    val_llm = _FakeStreamLLM(VALUATION_REPORT)
    coord, ws = _make_coord(
        tmp_path, quant_llm=quant_llm, valuation_llm=val_llm, sent=sent
    )

    ref = StockRef(code="002594.SZ", name="比亚迪", market="A")
    await coord.run(session_id="s1", message=ref.code, context=None)

    # Coordinator 应在 repo 上调 set_output_dir 或 update,记录 output_dir
    # 接受 set_output_dir / update 任一形式
    d = ws.resolve_dir(ref)
    repo = coord.repo
    called = False
    for name in ("set_output_dir", "update", "set_session_output_dir", "upsert"):
        m = getattr(repo, name, None)
        if m is None:
            continue
        for call in m.call_args_list:
            if str(d) in str(call):
                called = True
                break
    assert called, "coordinator 应把 output_dir 写回 session repo"
