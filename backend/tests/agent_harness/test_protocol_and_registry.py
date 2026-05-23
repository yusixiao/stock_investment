"""Agent registry + routing 单元测试。"""

import pytest

from services.agent_harness import registry, routing
from services.agent_harness.protocol import AgentManifest


@pytest.fixture(autouse=True)
def _clean_registry():
    registry._clear()
    yield
    registry._clear()


def _mk(id_: str, aliases: list[str], enabled: bool = True) -> AgentManifest:
    return {
        "id": id_,
        "label": id_.upper(),
        "aliases": aliases,
        "description": "test",
        "version": "1.0.0",
        "steps": [],
        "requires": [],
        "enabled": enabled,
    }


def test_register_and_get():
    m = _mk("cpa_conservative", ["保守分析", "保守"])
    registry.register(m, agent_factory=lambda: object())
    assert registry.exists("cpa_conservative")
    assert registry.get_manifest("cpa_conservative")["label"] == "CPA_CONSERVATIVE"


def test_register_duplicate_raises():
    m = _mk("a", ["A"])
    registry.register(m, lambda: None)
    with pytest.raises(ValueError):
        registry.register(m, lambda: None)


def test_list_only_enabled_filter():
    registry.register(_mk("a", ["A"]), lambda: None)
    registry.register(_mk("b", ["B"], enabled=False), lambda: None)
    assert {m["id"] for m in registry.list_manifests()} == {"a", "b"}
    assert {m["id"] for m in registry.list_manifests(only_enabled=True)} == {"a"}


def test_routing_keyword_match():
    registry.register(_mk("cpa_conservative", ["保守分析", "保守"]), lambda: None)
    registry.register(_mk("tradingagents_astock", ["团队分析", "团队"]), lambda: None)
    aid, reason = routing.resolve_agent(
        message="请用保守分析帮我看一下 002594",
        explicit_agent_id=None,
        default_agent_id="cpa_conservative",
    )
    assert (aid, reason) == ("cpa_conservative", "keyword")
    aid, reason = routing.resolve_agent(
        message="团队分析 600519",
        explicit_agent_id=None,
        default_agent_id="cpa_conservative",
    )
    assert (aid, reason) == ("tradingagents_astock", "keyword")


def test_routing_explicit_overrides_keyword():
    registry.register(_mk("cpa_conservative", ["保守"]), lambda: None)
    registry.register(_mk("tradingagents_astock", ["团队"]), lambda: None)
    aid, reason = routing.resolve_agent(
        message="保守分析 002594",
        explicit_agent_id="tradingagents_astock",
        default_agent_id="cpa_conservative",
    )
    assert (aid, reason) == ("tradingagents_astock", "explicit")


def test_routing_default_when_no_match():
    registry.register(_mk("cpa_conservative", ["保守"]), lambda: None)
    aid, reason = routing.resolve_agent(
        message="002594 怎么样",
        explicit_agent_id=None,
        default_agent_id="cpa_conservative",
    )
    assert (aid, reason) == ("cpa_conservative", "default")


def test_routing_default_missing_raises():
    registry.register(_mk("cpa_conservative", ["保守"]), lambda: None)
    with pytest.raises(RuntimeError):
        routing.resolve_agent(
            message="002594", explicit_agent_id=None, default_agent_id="ghost"
        )


def test_routing_disabled_agent_match_still_returned():
    """禁用 agent 仍可被关键字命中,由 dispatcher 在 dispatch 时拒绝。"""
    registry.register(
        _mk("tradingagents_astock", ["团队分析"], enabled=False), lambda: None
    )
    registry.register(_mk("cpa_conservative", ["保守"]), lambda: None)
    aid, _ = routing.resolve_agent(
        message="团队分析 002594",
        explicit_agent_id=None,
        default_agent_id="cpa_conservative",
    )
    assert aid == "tradingagents_astock"
