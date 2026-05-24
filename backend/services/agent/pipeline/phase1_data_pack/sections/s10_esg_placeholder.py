"""§10 ESG 与争议事件 — Phase 1 占位。

Phase 2 实现计划:
- 数据源:WebSearch(近 12 个月新闻 / 监管处罚 / 诉讼公告)+ 可选 MSCI ESG API
- 落地:Coordinator 新增 web_search 阶段,提取负面事件摘要
- LLM 用途:Phase 3.2 估值阶段提示治理风险,影响安全边际
"""

from __future__ import annotations


def build(ref, **kw) -> str:
    return (
        "## §10 ESG 与争议事件\n\n"
        "> 数据待补(Phase 2 接 WebSearch)。LLM 如需提示 ESG / 治理风险,"
        "请明确标注「未检索到实时争议事件,以下为先验印象」。\n\n"
        "**计划维度**:近 12 个月监管处罚、重大诉讼、安全 / 环保事故、ESG 评级变动。\n"
    )
