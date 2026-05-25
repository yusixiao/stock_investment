"""D3 行业周期与定位(骨架占位)。

阶段 2 真实实现要做:
  - Tavily search 行业景气度 / 周期阶段
  - DuckDB 营收波动率(近 5 年标准差/均值)
  - 输出 cyclicality + (强周期时)cycle_position
  - industry_keywords 用于 Agent C 事件监控
"""

from __future__ import annotations

from typing import Any

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


async def mock_dimension_d3(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
) -> tuple[DimensionReport, dict[str, Any]]:
    dim = DimensionReport(
        name="D3",
        title="行业周期与定位",
        narrative=f"[占位] {ref.code} D3 行业周期分析待 Phase 2 接入。",
        evidence=[],
    )
    partial = {
        "cyclicality": "弱周期",
        "industry_keywords": [],
    }
    return dim, partial
