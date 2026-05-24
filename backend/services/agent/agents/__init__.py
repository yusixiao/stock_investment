"""问股 agent 注册表。

每个 agent 是一个自包含子包,实现 `Agent.run(...) -> AsyncIterator[SSEEvent]` 契约。
Coordinator 通过 AGENT_REGISTRY 查找 agent。
"""

from __future__ import annotations

from typing import Dict, Type

from services.agent.agents.cpa.agent import CpaAgent

AGENT_REGISTRY: Dict[str, Type] = {
    "cpa": CpaAgent,
}
