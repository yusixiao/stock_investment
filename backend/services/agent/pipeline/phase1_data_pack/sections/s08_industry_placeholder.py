"""§8 行业竞争与监管 — Phase 1 占位。

Phase 2 实现计划:
- 数据源:WebSearch(行业研报、政策公告、竞争格局)
- 落地:Coordinator 新增 web_search 阶段,把摘要注入数据包
- LLM 用途:Phase 3.2 估值阶段判定行业景气度、政策风险、护城河
"""

from __future__ import annotations


def build(ref, **kw) -> str:
    return (
        "## §8 行业竞争与监管\n\n"
        "> 数据待补(Phase 2 接 WebSearch)。LLM 在估值阶段如需评估行业景气度 / 政策风险,"
        "请基于自身先验知识给出谨慎判断,并明确标注「该结论未经实时数据验证」。\n\n"
        "**计划维度**:行业增速、CR5 集中度、近 6 个月监管政策、技术替代风险。\n"
    )
