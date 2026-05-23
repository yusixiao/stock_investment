"""三个 agent 注册 + dispatcher 行为冒烟测试。"""

import asyncio

import pytest

from services.agent_harness import dispatcher, registry


def _collect(aiter):
    async def _go():
        out = []
        async for ev in aiter:
            out.append(ev)
        return out

    return asyncio.run(_go())


class _Ref:
    symbol, name, market = "002594.SZ", "比亚迪", "A"


class _LLM:
    model, channel = "test", "test"

    async def stream(self, prompt, **kw):
        for c in "你好,问股助手在线。":
            yield c


def test_three_agents_registered_in_phase1():
    ids = {m["id"] for m in registry.list_manifests()}
    assert {"cpa_conservative", "tradingagents_astock", "chitchat"} <= ids
    enabled = {m["id"] for m in registry.list_manifests(only_enabled=True)}
    assert "cpa_conservative" in enabled
    assert "chitchat" in enabled
    assert "tradingagents_astock" not in enabled


def test_tradingagents_astock_returns_graceful_error(tmp_path, monkeypatch):
    monkeypatch.setattr("services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    out = _collect(
        dispatcher.dispatch(
            agent_id="tradingagents_astock",
            ref=_Ref(),
            llm=_LLM(),
            session_id="s-team",
        )
    )
    types = [e["type"] for e in out]
    assert types == ["error"]
    assert "团队分析" in out[0]["message"]
    assert "暂未上线" in out[0]["message"]


def test_chitchat_agent_streams(tmp_path, monkeypatch):
    monkeypatch.setattr("services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    out = _collect(
        dispatcher.dispatch(
            agent_id="chitchat", ref=_Ref(), llm=_LLM(), session_id="s-chit"
        )
    )
    types = [e["type"] for e in out]
    assert types[0] == "thinking"
    assert "generating" in types
    assert types[-1] == "done"
    assert "tool_start" not in types  # 闲聊无 step


def test_cpa_conservative_manifest_exposes_three_steps():
    m = registry.get_manifest("cpa_conservative")
    step_ids = [s["id"] for s in m["steps"]]
    assert step_ids == ["data_pack", "quant", "valuation"]
    assert m["label"] == "保守分析"
    assert "保守分析" in m["aliases"]


def test_cpa_conservative_placeholder_raises_not_implemented(tmp_path, monkeypatch):
    monkeypatch.setattr("services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    out = _collect(
        dispatcher.dispatch(
            agent_id="cpa_conservative",
            ref=_Ref(),
            llm=_LLM(),
            session_id="s-cpa",
        )
    )
    types = [e["type"] for e in out]
    # 占位 agent raise NotImplementedError -> dispatcher 捕获 -> error 事件
    assert "thinking" in types
    assert types[-1] == "error"
    assert "T20-T31" in out[-1]["message"]
