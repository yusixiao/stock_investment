"""D6 控股结构与 SOTP(骨架占位)。

阶段 2 真实实现要做:
  - EastMoney F10 股东表 + 子公司明细
  - 判定 holding_structure(是否为多业务控股平台)
  - 控股型公司 → 估算 sotp_discount_pct(0-1)
"""

from __future__ import annotations

from typing import Any

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


async def mock_dimension_d6(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
) -> tuple[DimensionReport, dict[str, Any]]:
    dim = DimensionReport(
        name="D6",
        title="控股结构与 SOTP",
        narrative=f"[占位] {ref.code} D6 控股结构分析待 Phase 2 接入 F10 股东表。",
        evidence=[],
    )
    partial = {"holding_structure": False}
    return dim, partial
