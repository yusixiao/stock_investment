"""保守分析 agent 入口 — 占位实现,待 r1 T20-T31 填实。"""

from services.agent_harness import registry

from .manifest import MANIFEST


class _Placeholder:
    """T20-T31 实施前的占位。实施时替换为真 CPAConservativeAgent。"""

    manifest = MANIFEST

    async def run(self, *, ref, llm, ctx):
        raise NotImplementedError("cpa_conservative agent 待 r1 T20-T31 实施完成")
        yield  # async generator marker


registry.register(MANIFEST, agent_factory=_Placeholder)
