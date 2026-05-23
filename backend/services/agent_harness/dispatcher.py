"""Agent dispatcher:统一入口,根据 agent_id 路由到具体实现。

职责:
- 校验 agent 存在 + enabled
- 创建 workspace + 初始化 _meta.json
- 包装 thinking 事件作为前导
- 流式转发 agent.run() 产出的事件,补全 agent_id/agent_label,同步更新 meta
- 异常兜底:NotImplementedError / 其他 Exception → 写 failed + emit error
"""

from __future__ import annotations

from typing import AsyncIterator

from . import events, registry
from .meta import finalize_meta, init_meta, update_meta_from_event
from .protocol import Event
from .workspace import create_workspace


async def dispatch(*, agent_id: str, ref, llm, session_id: str) -> AsyncIterator[Event]:
    if not registry.exists(agent_id):
        yield events.error(agent_id=agent_id, message=f"未知 agent: {agent_id}")
        return
    manifest = registry.get_manifest(agent_id)
    if not manifest.get("enabled", True):
        yield events.error(
            agent_id=agent_id,
            message=f"{manifest['label']} agent 暂未上线,请使用其他分析方式。",
        )
        return

    agent = registry.get_agent(agent_id)
    workspace = create_workspace(session_id=session_id, agent_id=agent_id)
    meta = init_meta(workspace=workspace, manifest=manifest, ref=ref, llm=llm)

    class _Ctx:
        def __init__(self):
            self.workspace = workspace
            self.session_id = session_id

        async def emit(self, ev: Event) -> None:
            # dispatcher 已经在主循环中转发,agent 内部 emit 是可选钩子
            pass

        async def log_decision(self, step_id: str, payload: dict) -> None:
            pass

    ctx = _Ctx()

    yield events.thinking(
        agent_id=agent_id,
        agent_label=manifest["label"],
        message=f"开始分析 {getattr(ref, 'name', '') or getattr(ref, 'symbol', '')}",
    )
    try:
        async for ev in agent.run(ref=ref, llm=llm, ctx=ctx):
            ev.setdefault("agent_id", agent_id)
            ev.setdefault("agent_label", manifest["label"])
            update_meta_from_event(workspace, meta, ev)
            yield ev
        finalize_meta(workspace, meta, status="done")
    except NotImplementedError as e:
        finalize_meta(workspace, meta, status="failed", error=str(e))
        yield events.error(agent_id=agent_id, message=str(e))
    except Exception as e:
        finalize_meta(workspace, meta, status="failed", error=str(e))
        yield events.error(
            agent_id=agent_id, message=f"{manifest['label']} 执行失败:{e}"
        )
