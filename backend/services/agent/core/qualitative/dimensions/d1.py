"""D1 商业模式与资本特征(骨架占位)。

阶段 2 真实实现要做:
  - DuckDB 取近 5 年 capex / 折旧、应收账款周转
  - 判定 capital_intensity:capex/revenue 阈值
  - 判定 collection_mode:预收/应收/营收比例 + Tavily 行业惯例
  - 输出叙事 + (capital_intensity, collection_mode) partial
"""

from __future__ import annotations

from typing import Any

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


async def mock_dimension_d1(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
) -> tuple[DimensionReport, dict[str, Any]]:
    dim = DimensionReport(
        name="D1",
        title="商业模式与资本特征",
        narrative=f"[占位] {ref.code} D1 商业模式分析待 Phase 2 接入真实数据。",
        evidence=[],
    )
    partial = {
        "capital_intensity": "capital-light",
        "collection_mode": "先款后货",
    }
    return dim, partial
