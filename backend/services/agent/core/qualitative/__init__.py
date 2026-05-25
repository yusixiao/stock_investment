"""问股 · 定性分析共享 service(business-analysis 模块)。

按 plan_business_analysis_agent.md 方案 C:
  - core/qualitative/ 提供共享能力(schema / cache / runner / 6 维度函数)
  - agents/business_analysis/ 暴露用户入口(SSE 事件流)
  - agents/cpa/pipeline/phase0_qualitative.py 作为前置阶段集成

公开 API:
  - QualitativeParams / DimensionReport / QualitativeReport(schema 模型)
  - QualitativeCache(30 天 TTL + REPORT_DATE 失效)
  - run_qualitative(ref, *, on_event=None, force_refresh=False)(异步主入口)
"""

from services.agent.core.qualitative.cache import QualitativeCache
from services.agent.core.qualitative.runner import run_qualitative
from services.agent.core.qualitative.schema import (
    DimensionReport,
    QualitativeParams,
    QualitativeReport,
    map_moat_rating_turtle,
)

__all__ = [
    "QualitativeParams",
    "DimensionReport",
    "QualitativeReport",
    "QualitativeCache",
    "run_qualitative",
    "map_moat_rating_turtle",
]
