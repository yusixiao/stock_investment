"""Dispatcher 集成测试 — 校验事件流 + meta 写盘。"""

import asyncio
import json

import pytest

from services.agent_harness import dispatcher, events as E, registry


@pytest.fixture(autouse=True)
def _clean():
    registry._clear()
    yield
    registry._clear()


class _Ref:
    symbol, name, market = "002594.SZ", "比亚迪", "A"


class _LLM:
    model, channel = "test-model", "test-ch"

    async def stream(self, prompt, **kw):
        yield "ok"


def _collect(aiter):
    async def _go():
        out = []
        async for ev in aiter:
            out.append(ev)
        return out

    return asyncio.run(_go())


def test_dispatch_unknown_agent(tmp_path, monkeypatch):
    monkeypatch.setattr("services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    out = _collect(
        dispatcher.dispatch(agent_id="ghost", ref=_Ref(), llm=_LLM(), session_id="s1")
    )
    assert len(out) == 1 and out[0]["type"] == "error"
    assert "未知" in out[0]["message"]


def test_dispatch_disabled_agent(tmp_path, monkeypatch):
    monkeypatch.setattr("services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)
    registry.register(
        {
            "id": "team",
            "label": "团队分析",
            "aliases": [],
            "description": "",
            "version": "0",
            "steps": [],
            "requires": [],
            "enabled": False,
        },
        lambda: object(),
    )
    out = _collect(
        dispatcher.dispatch(agent_id="team", ref=_Ref(), llm=_LLM(), session_id="s2")
    )
    assert out[0]["type"] == "error" and "暂未上线" in out[0]["message"]


def test_dispatch_runs_agent_and_writes_meta(tmp_path, monkeypatch):
    monkeypatch.setattr("services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)

    class _A:
        manifest = {
            "id": "demo",
            "label": "Demo",
            "aliases": [],
            "description": "",
            "version": "1.0.0",
            "steps": [{"id": "s1", "label": "Step1", "estimated_seconds": 1}],
            "requires": [],
            "enabled": True,
        }

        async def run(self, *, ref, llm, ctx):
            yield E.tool_start(
                agent_id="demo",
                agent_label="Demo",
                step_id="s1",
                step_label="Step1",
                step_index=1,
                step_total=1,
            )
            yield E.generating(agent_id="demo", step_id="s1", delta="hello")
            yield E.tool_done(agent_id="demo", step_id="s1")
            yield E.done(agent_id="demo")

    registry.register(_A.manifest, lambda: _A())
    out = _collect(
        dispatcher.dispatch(agent_id="demo", ref=_Ref(), llm=_LLM(), session_id="s3")
    )
    types = [e["type"] for e in out]
    assert types == ["thinking", "tool_start", "generating", "tool_done", "done"]
    # 所有事件都注入了 agent_id
    assert all(e["agent_id"] == "demo" for e in out)
    # _meta.json 已写
    runs = list(tmp_path.glob("s3/demo__*/_meta.json"))
    assert len(runs) == 1
    meta = json.loads(runs[0].read_text(encoding="utf-8"))
    assert meta["status"] == "done"
    assert meta["agent_id"] == "demo"
    assert meta["steps"]["s1"]["status"] == "done"


def test_dispatch_agent_raises_writes_failed(tmp_path, monkeypatch):
    monkeypatch.setattr("services.agent_harness.workspace.WORKSPACE_ROOT", tmp_path)

    class _Boom:
        manifest = {
            "id": "boom",
            "label": "Boom",
            "aliases": [],
            "description": "",
            "version": "1.0.0",
            "steps": [],
            "requires": [],
            "enabled": True,
        }

        async def run(self, *, ref, llm, ctx):
            if False:
                yield  # async generator marker
            raise RuntimeError("kaboom")

    registry.register(_Boom.manifest, lambda: _Boom())
    out = _collect(
        dispatcher.dispatch(agent_id="boom", ref=_Ref(), llm=_LLM(), session_id="s4")
    )
    types = [e["type"] for e in out]
    assert types[-1] == "error"
    assert "kaboom" in out[-1]["message"]
    runs = list(tmp_path.glob("s4/boom__*/_meta.json"))
    meta = json.loads(runs[0].read_text(encoding="utf-8"))
    assert meta["status"] == "failed"
    assert "kaboom" in meta["error"]
