"""D2 护城河与竞争格局(骨架占位)。

阶段 2 真实实现要做:
  - Tavily search 公司护城河类型 + 飞轮效应
  - EastMoney F10 主营构成 → 行业地位
  - LLM 综合 → moat_type / moat_flywheel / moat_rating
  - 列出主要竞争对手(name, ticker)
"""

from __future__ import annotations

from typing import Any

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


async def mock_dimension_d2(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
) -> tuple[DimensionReport, dict[str, Any]]:
    dim = DimensionReport(
        name="D2",
        title="护城河与竞争格局",
        narrative=f"[占位] {ref.code} D2 护城河分析待 Phase 2 接入 Tavily + F10。",
        evidence=[],
    )
    partial = {
        "moat_type": "[占位] 待识别",
        "moat_flywheel": False,
        "moat_rating": "中",
        "competitors": [],
    }
    return dim, partial
