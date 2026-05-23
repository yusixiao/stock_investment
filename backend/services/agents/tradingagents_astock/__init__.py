"""团队分析 agent 入口 — 期 1 仅占位,enabled=False(dispatcher 短路)。"""

from services.agent_harness import registry

from .manifest import MANIFEST


class _TradingAgent:
    manifest = MANIFEST

    async def run(self, *, ref, llm, ctx):
        # dispatcher 在 enabled=False 时已短路,这里只做防御
        raise NotImplementedError(
            "团队分析 agent 计划于期 2 上线,基于 TradingAgents-Astock 多角色辩论框架。"
        )
        yield


registry.register(MANIFEST, agent_factory=_TradingAgent)
