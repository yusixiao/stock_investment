"""Phase 3.2 — 估值与最终报告组装。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol

from services.agent.prompts import loader


class StreamLLM(Protocol):
    async def stream(self, prompt: str, **kwargs) -> Any: ...


OnChunk = Optional[Callable[[str], Awaitable[None]]]


def _safe_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in s).strip() or "report"


async def run_phase3_valuation(
    *,
    workspace: Path,
    llm: StreamLLM,
    company_name: str,
    symbol: str,
    quant_results: dict[str, Any],
    on_chunk: OnChunk = None,
) -> Path:
    """执行 Phase 3.2,返回最终报告路径。"""
    pack_path = workspace / "data_pack_market.md"
    quant_path = workspace / "phase3_quantitative.md"
    if not pack_path.exists():
        raise FileNotFoundError(f"data_pack_market.md 不存在于 {workspace}")
    if not quant_path.exists():
        raise FileNotFoundError(f"phase3_quantitative.md 不存在于 {workspace}")

    (workspace / "_quant_results.json").write_text(
        json.dumps(quant_results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    instr = loader.load(
        "phase3_valuation.md",
        expand_includes=True,
        output_dir=str(workspace),
    )

    pack_text = pack_path.read_text(encoding="utf-8")
    quant_text = quant_path.read_text(encoding="utf-8")
    quant_json = json.dumps(quant_results, ensure_ascii=False, indent=2)

    prompt = (
        instr
        + f"\n\n---\n\n## 公司信息\n- 公司名:{company_name}\n- 股票代码:{symbol}\n"
        + "\n\n## Phase 3.1 量化报告(完整)\n<phase3_quantitative>\n"
        + quant_text
        + "\n</phase3_quantitative>"
        + "\n\n## Phase 3.1 解析后关键参数\n```json\n"
        + quant_json
        + "\n```"
        + "\n\n## 原始数据包\n<data_pack_market>\n"
        + pack_text
        + "\n</data_pack_market>"
        + "\n\n请严格按 phase3_valuation.md 中 <report_template> 输出完整 markdown 报告。"
    )

    fname = f"{_safe_filename(company_name)}_{_safe_filename(symbol)}_分析报告.md"
    out_path = workspace / fname
    with out_path.open("w", encoding="utf-8") as f:
        async for chunk in llm.stream(prompt):
            if not chunk:
                continue
            f.write(chunk)
            f.flush()
            if on_chunk is not None:
                await on_chunk(chunk)
    return out_path
