"""Harness 事件工厂(与 services/agent/sse.py 不同:harness 用于 agent 内部传播,
SSE 层另有契约;dispatcher 输出最终被 SSE 编码)。"""

from __future__ import annotations

from .protocol import Event


def thinking(*, agent_id: str, agent_label: str, message: str) -> Event:
    return {
        "type": "thinking",
        "agent_id": agent_id,
        "agent_label": agent_label,
        "message": message,
    }


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
