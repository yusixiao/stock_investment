"""D4 管理层与治理(骨架占位)。

阶段 2 真实实现要做:
  - EastMoney F10 高管表 + 持股
  - Tavily 治理事件(诉讼/处罚/关联交易)
  - LLM 综合 → management_rating
"""

from __future__ import annotations

from typing import Any

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


async def mock_dimension_d4(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
) -> tuple[DimensionReport, dict[str, Any]]:
    dim = DimensionReport(
        name="D4",
        title="管理层与治理",
        narrative=f"[占位] {ref.code} D4 管理层分析待 Phase 2 接入 F10 + Tavily。",
        evidence=[],
    )
    partial = {"management_rating": "合格"}
    return dim, partial
