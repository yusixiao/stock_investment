"""问股期 1 — Task 29:Phase 3.1 量化执行器测试。"""

import asyncio

import pytest

from services.agent.pipeline.phase3_quant import run_phase3_quant


class _FakeStreamLLM:
    """Fake LLM:把固定字符串按 chunk 流回。"""

    def __init__(self, full_text: str, chunks: int = 4):
        self.full_text = full_text
        self.chunks = chunks
        self.last_prompt: str | None = None

    async def stream(self, prompt: str, **kwargs):
        self.last_prompt = prompt
        size = max(1, len(self.full_text) // self.chunks)
        for i in range(0, len(self.full_text), size):
            yield self.full_text[i : i + size]


REPORT = """# Phase 3 定量分析

## Step 11 输出

<results>
owner_earnings_I=4523.5
final_return_GG=11.2
threshold_II=10.5
margin_KK=0.7
trap_risk=低
extrapolation_confidence=中
</results>
"""


def test_run_phase3_quant_writes_report_and_parses(tmp_path):
    (tmp_path / "data_pack_market.md").write_text(
        "# §1 ...\n## §3 ...\n", encoding="utf-8"
    )
    llm = _FakeStreamLLM(REPORT)
    chunks_received: list[str] = []

    async def on_chunk(s: str):
        chunks_received.append(s)

    out_path, parsed = asyncio.run(
        run_phase3_quant(workspace=tmp_path, llm=llm, on_chunk=on_chunk)
    )
    assert out_path == tmp_path / "phase3_quantitative.md"
    assert out_path.read_text(encoding="utf-8") == REPORT
    assert parsed["final_return_GG"] == 11.2
    assert parsed["trap_risk"] == "低"
    assert len(chunks_received) >= 2
    assert "§1" in llm.last_prompt or "data_pack_market" in llm.last_prompt


def test_run_phase3_quant_missing_pack_raises(tmp_path):
    llm = _FakeStreamLLM(REPORT)
    with pytest.raises(FileNotFoundError):
        asyncio.run(run_phase3_quant(workspace=tmp_path, llm=llm, on_chunk=None))
