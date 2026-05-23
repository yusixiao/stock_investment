"""routing.resolve_agent 4 层 fallback 集成测试。"""

import asyncio
import importlib
import json

import pytest

from services.agent_harness import registry, routing


@pytest.fixture(autouse=True)
def _registered_agents():
    """重新触发 services.agents 注册,确保 cpa_conservative / tradingagents_astock / chitchat 都在 registry。"""
    import services.agents  # noqa: F401

    registry._clear()
    importlib.reload(importlib.import_module("services.agents.cpa_conservative"))
    importlib.reload(importlib.import_module("services.agents.tradingagents_astock"))
    importlib.reload(importlib.import_module("services.agents.chitchat"))
    yield
    registry._clear()


class _StubLLM:
    def __init__(self, raw):
        self.raw = raw

    async def complete_json(self, *, system, user, timeout=10):
        return self.raw


def _run(coro):
    return asyncio.run(coro)


def test_explicit_short_circuits_llm():
    """显式 agent_id 提供时,根本不调 LLM。"""
    llm = _StubLLM("should-not-be-called")
    decision = _run(
        routing.resolve_agent(
            message="任意消息",
            explicit_agent_id="cpa_conservative",
            default_agent_id="cpa_conservative",
            llm=llm,
        )
    )
    assert decision.reason == "explicit"
    assert decision.agent_id == "cpa_conservative"


def test_keyword_short_circuits_llm():
    decision = _run(
        routing.resolve_agent(
            message="保守分析这只票",
            explicit_agent_id=None,
            default_agent_id="cpa_conservative",
            llm=_StubLLM("never"),
        )
    )
    assert decision.reason == "keyword"
    assert decision.agent_id == "cpa_conservative"


def test_llm_router_high_confidence_used():
    raw = json.dumps(
        {
            "agent_id": "cpa_conservative",
            "confidence": 0.85,
            "reason": "x",
            "needs_clarification": False,
            "clarification_question": "",
        }
    )
    decision = _run(
        routing.resolve_agent(
            message="这只股票怎么样",
            explicit_agent_id=None,
            default_agent_id="cpa_conservative",
            llm=_StubLLM(raw),
        )
    )
    assert decision.reason == "llm"
    assert decision.confidence >= 0.6


def test_llm_router_low_confidence_returns_clarify():
    raw = json.dumps(
        {
            "agent_id": None,
            "confidence": 0.3,
            "reason": "模糊",
            "needs_clarification": True,
            "clarification_question": "你是想做保守分析还是团队分析?",
        }
    )
    decision = _run(
        routing.resolve_agent(
            message="帮帮我啊",
            explicit_agent_id=None,
            default_agent_id="cpa_conservative",
            llm=_StubLLM(raw),
        )
    )
    assert decision.reason == "clarify"
    assert decision.agent_id is None
    assert decision.clarification_question
    assert decision.quick_replies
    assert any(r["agent_id"] == "cpa_conservative" for r in decision.quick_replies)


def test_llm_picks_disabled_agent_falls_back_to_clarify():
    raw = json.dumps(
        {
            "agent_id": "tradingagents_astock",
            "confidence": 0.9,
            "reason": "x",
            "needs_clarification": False,
            "clarification_question": "",
        }
    )
    decision = _run(
        routing.resolve_agent(
            message="这只股票怎么样",
            explicit_agent_id=None,
            default_agent_id="cpa_conservative",
            llm=_StubLLM(raw),
        )
    )
    # disabled agent 即使高 confidence,也应降级到 clarify(让用户重选)
    assert decision.reason == "clarify"


def test_message_too_short_skips_llm_returns_default():
    """消息 < 4 字符直接走 default,不调 LLM。"""
    decision = _run(
        routing.resolve_agent(
            message="嗯",
            explicit_agent_id=None,
            default_agent_id="cpa_conservative",
            llm=_StubLLM("never"),
        )
    )
    assert decision.reason == "default"


def test_mention_routes_to_agent_id():
    decision = _run(
        routing.resolve_agent(
            message="@chitchat 帮我介绍一下",
            explicit_agent_id=None,
            default_agent_id="cpa_conservative",
            llm=_StubLLM("never"),
        )
    )
    assert decision.reason == "mention"
    assert decision.agent_id == "chitchat"
