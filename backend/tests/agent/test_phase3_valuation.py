"""问股期 1 — Task 30:Phase 3.2 估值执行器测试。"""

import asyncio

from services.agent.pipeline.phase3_valuation import run_phase3_valuation


class _FakeStreamLLM:
    def __init__(self, text: str):
        self.text = text
        self.last_prompt: str | None = None

    async def stream(self, prompt: str, **kwargs):
        self.last_prompt = prompt
        for i in range(0, len(self.text), 200):
            yield self.text[i : i + 200]


FINAL_REPORT = """# 龟龟投资策略 · 分析报告:比亚迪(002594.SZ)

## Executive Summary
**仓位建议**:观察

| 指标 | 值 |
|---|---|
| Owner Earnings | 4,523.5 百万 |
| 精算穿透回报率 | 11.2% |
"""


def test_run_phase3_valuation_writes_named_report(tmp_path):
    (tmp_path / "data_pack_market.md").write_text(
        "# §1\n基本信息: 比亚迪 002594.SZ\n", encoding="utf-8"
    )
    (tmp_path / "phase3_quantitative.md").write_text(
        "# 量化\n<results>\nfinal_return_GG=11.2\n</results>\n",
        encoding="utf-8",
    )

    llm = _FakeStreamLLM(FINAL_REPORT)
    chunks: list[str] = []

    async def on_chunk(s):
        chunks.append(s)

    out_path = asyncio.run(
        run_phase3_valuation(
            workspace=tmp_path,
            llm=llm,
            company_name="比亚迪",
            symbol="002594.SZ",
            quant_results={"final_return_GG": 11.2, "trap_risk": "低"},
            on_chunk=on_chunk,
        )
    )
    assert out_path.name == "比亚迪_002594.SZ_分析报告.md"
    assert out_path.read_text(encoding="utf-8") == FINAL_REPORT
    assert len(chunks) >= 1
    assert "final_return_GG" in llm.last_prompt and "11.2" in llm.last_prompt
    assert "比亚迪" in llm.last_prompt
    # _quant_results.json 也应被持久化
    assert (tmp_path / "_quant_results.json").exists()
