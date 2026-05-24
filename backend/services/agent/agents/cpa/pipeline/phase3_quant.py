"""Phase 3.1 — CPA 量化(穿透回报率精算)阶段编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol

from services.agent.core.parser import parse_phase3_quant_results
from services.agent.agents.cpa import prompts as loader


class StreamLLM(Protocol):
    async def stream(self, prompt: str, **kwargs) -> Any: ...


OnChunk = Optional[Callable[[str], Awaitable[None]]]


async def run_phase3_quant(
    *,
    workspace: Path,
    llm: StreamLLM,
    on_chunk: OnChunk = None,
) -> tuple[Path, dict[str, Any]]:
    """执行 Phase 3.1:读 data_pack → 拼 prompt → stream LLM → 写报告 → 解析。"""
    pack_path = workspace / "data_pack_market.md"
    if not pack_path.exists():
        raise FileNotFoundError(f"data_pack_market.md 不存在于 {workspace}")
    pack_text = pack_path.read_text(encoding="utf-8")

    extra = ""
    report_pack = workspace / "data_pack_report.md"
    if report_pack.exists():
        extra = (
            "\n\n<data_pack_report>\n"
            + report_pack.read_text(encoding="utf-8")
            + "\n</data_pack_report>"
        )

    instr = loader.load(
        "phase3_quantitative.md",
        expand_includes=True,
        output_dir=str(workspace),
    )

    prompt = (
        instr
        + "\n\n---\n\n## 输入数据包\n\n"
        + "<data_pack_market>\n"
        + pack_text
        + "\n</data_pack_market>"
        + extra
        + "\n\n请按上述 Step 0~11 顺序输出完整报告,末尾必须含 <results>...</results> 块。"
    )

    out_path = workspace / "phase3_quantitative.md"
    parts: list[str] = []
    with out_path.open("w", encoding="utf-8") as f:
        async for chunk in llm.stream(prompt):
            if not chunk:
                continue
            f.write(chunk)
            f.flush()
            parts.append(chunk)
            if on_chunk is not None:
                await on_chunk(chunk)

    full_text = "".join(parts)
    parsed = parse_phase3_quant_results(full_text)
    return out_path, parsed
