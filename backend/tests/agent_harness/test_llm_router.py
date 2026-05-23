"""LLM router classify() 单元测试 — 用 _StubLLM 模拟 complete_json。"""

import asyncio
import json

import pytest

from services.agent_harness import llm_router, registry


# 注:llm_router.classify 不依赖 registry,直接传 agents 列表;
# 这里 fixture 只为方便构造候选池。
@pytest.fixture
def agents():
    return [
        {
            "id": "cpa_conservative",
            "label": "保守分析",
            "description": "穿透回报率精算",
            "aliases": ["保守分析", "保守"],
        },
        {
            "id": "chitchat",
            "label": "闲聊",
            "description": "通用对话",
            "aliases": [],
        },
    ]


class _StubLLM:
    """可编程 LLM:complete_json 返回预设 raw 字符串。"""

    def __init__(
        self, raw: str, *, raise_exc: Exception | None = None, sleep: float = 0.0
    ):
        self.raw = raw
        self.raise_exc = raise_exc
        self.sleep = sleep
        self.calls = []

    async def complete_json(self, *, system: str, user: str, timeout: float = 10):
        self.calls.append({"system": system, "user": user, "timeout": timeout})
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.raise_exc:
            raise self.raise_exc
        return self.raw


def test_high_confidence_returns_decision(agents):
    raw = json.dumps(
        {
            "agent_id": "cpa_conservative",
            "confidence": 0.9,
            "reason": "用户问长期持有,适合保守分析",
            "needs_clarification": False,
            "clarification_question": "",
        }
    )
    llm = _StubLLM(raw)
    decision = asyncio.run(
        llm_router.classify(message="这只股票适合长期持有吗", llm=llm, agents=agents)
    )
    assert decision.agent_id == "cpa_conservative"
    assert decision.confidence == pytest.approx(0.9)
    assert decision.needs_clarification is False
    # prompt 包含候选 agents
    assert "cpa_conservative" in llm.calls[0]["system"]
    assert "保守分析" in llm.calls[0]["system"]


def test_low_confidence_triggers_clarification(agents):
    raw = json.dumps(
        {
            "agent_id": None,
            "confidence": 0.4,
            "reason": "请求模糊",
            "needs_clarification": True,
            "clarification_question": "你是想做保守分析还是团队分析?",
        }
    )
    decision = asyncio.run(
        llm_router.classify(message="我该买还是卖", llm=_StubLLM(raw), agents=agents)
    )
    assert decision.needs_clarification is True
    assert "保守分析" in decision.clarification_question


def test_invalid_json_falls_back_to_clarification(agents):
    decision = asyncio.run(
        llm_router.classify(
            message="??", llm=_StubLLM("not a json {bad"), agents=agents
        )
    )
    assert decision.needs_clarification is True
    assert decision.confidence == 0.0
    assert "保守分析" in decision.clarification_question


def test_llm_exception_falls_back_to_clarification(agents):
    decision = asyncio.run(
        llm_router.classify(
            message="hi",
            llm=_StubLLM("", raise_exc=RuntimeError("network")),
            agents=agents,
        )
    )
    assert decision.needs_clarification is True
    assert decision.confidence == 0.0


def test_timeout_falls_back_to_clarification(agents):
    decision = asyncio.run(
        llm_router.classify(
            message="hi",
            llm=_StubLLM("", raise_exc=asyncio.TimeoutError()),
            agents=agents,
        )
    )
    assert decision.needs_clarification is True


def test_empty_agents_pool_returns_clarify():
    decision = asyncio.run(
        llm_router.classify(message="x", llm=_StubLLM(""), agents=[])
    )
    assert decision.needs_clarification is True


def test_disabled_agent_in_response_passes_through(agents):
    """classify 层不主动过滤;由 routing.resolve_agent 在 enabled 校验时拒绝。"""
    raw = json.dumps(
        {
            "agent_id": "tradingagents_astock",
            "confidence": 0.95,
            "reason": "想要团队",
            "needs_clarification": False,
            "clarification_question": "",
        }
    )
    decision = asyncio.run(
        llm_router.classify(message="团队", llm=_StubLLM(raw), agents=agents)
    )
    assert decision.agent_id == "tradingagents_astock"
