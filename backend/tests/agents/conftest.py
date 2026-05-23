"""Re-register agents before every test in this dir.

agent_harness 测试用 registry._clear() 自动清空 registry;agents 这边
依赖三个 agent 已注册,因此每个测试前用 importlib.reload 重新触发注册。
"""

import importlib

import pytest

from services.agent_harness import registry


@pytest.fixture(autouse=True)
def _ensure_agents_registered():
    # 先确保 agents 包加载过(可能首次加载就会注册一次)
    import services.agents  # noqa: F401

    # 然后清空 + 强制重新执行子模块 init,保证 registry 状态确定
    registry._clear()
    importlib.reload(importlib.import_module("services.agents.cpa_conservative"))
    importlib.reload(importlib.import_module("services.agents.tradingagents_astock"))
    importlib.reload(importlib.import_module("services.agents.chitchat"))
    yield
    registry._clear()
