"""问股 · 团队定性分析 agent(business-analysis)。

用户入口:在 coordinator 路由命中"定性 / 商业模式 / 护城河 / 管理层 / 周期性 / ..."
等关键词时触发,执行 6 维度定性分析并产出 markdown 报告。

实现细节见 agent.py / plan_business_analysis_agent.md。
"""

from services.agent.agents.business_analysis.agent import BusinessAnalysisAgent

__all__ = ["BusinessAnalysisAgent"]
