"""闲聊 agent 入口。"""

from services.agent_harness import registry

from .agent import ChitchatAgent
from .manifest import MANIFEST

registry.register(MANIFEST, agent_factory=ChitchatAgent)
