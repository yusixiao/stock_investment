"""Harness 事件工厂(与 services/agent/sse.py 不同:harness 用于 agent 内部传播,
SSE 层另有契约;dispatcher 输出最终被 SSE 编码)。"""

from __future__ import annotations

from .protocol import Event


def thinking(
    *,
    agent_id: str | None = None,
    agent_label: str | None = None,
    message: str | None = None,
    payload: dict | None = None,
) -> Event:
    """thinking 事件:agent 启动或路由澄清提示。

    - 普通用法: thinking(agent_id=..., agent_label=..., message=...)
    - 路由澄清: thinking(agent_id=None, agent_label="路由助手",
                          payload={"message": "...", "quick_replies": [...]})
    """
    ev: Event = {"type": "thinking"}
    if agent_id is not None:
        ev["agent_id"] = agent_id
    if agent_label is not None:
        ev["agent_label"] = agent_label
    if message is not None:
        ev["message"] = message
    if payload:
        ev.update(payload)  # type: ignore[arg-type]
    return ev


def tool_start(
    *,
    agent_id: str,
    agent_label: str,
    step_id: str,
    step_label: str,
    step_index: int,
    step_total: int,
) -> Event:
    return {
        "type": "tool_start",
        "agent_id": agent_id,
        "agent_label": agent_label,
        "step_id": step_id,
        "step_label": step_label,
        "step_index": step_index,
        "step_total": step_total,
    }


def tool_done(*, agent_id: str, step_id: str) -> Event:
    return {"type": "tool_done", "agent_id": agent_id, "step_id": step_id}


def generating(*, agent_id: str, step_id: str, delta: str) -> Event:
    return {
        "type": "generating",
        "agent_id": agent_id,
        "step_id": step_id,
        "delta": delta,
    }


def done(*, agent_id: str, report_path: str | None = None) -> Event:
    out: Event = {"type": "done", "agent_id": agent_id}
    if report_path:
        out["report_path"] = report_path
    return out


def error(*, agent_id: str, message: str) -> Event:
    return {"type": "error", "agent_id": agent_id, "message": message}
