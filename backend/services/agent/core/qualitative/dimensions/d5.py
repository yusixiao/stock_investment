"""D5 MD&A 可信度与导向(骨架占位)。

阶段 2 真实实现要做:
  - 获取年报 MD&A 段落(EastMoney 公告 / Tavily 抓取)
  - LLM 评估管理层口径与实际数据一致性
  - 输出 mda_credibility / mda_impact
"""

from __future__ import annotations

from typing import Any

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


async def mock_dimension_d5(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
) -> tuple[DimensionReport, dict[str, Any]]:
    dim = DimensionReport(
        name="D5",
        title="MD&A 可信度与导向",
        narrative=f"[占位] {ref.code} D5 MD&A 分析待 Phase 2 接入年报解析。",
        evidence=[],
    )
    partial = {
        "mda_credibility": "中",
        "mda_impact": "中性",
    }
    return dim, partial
