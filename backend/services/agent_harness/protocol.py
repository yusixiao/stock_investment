"""Agent Harness 类型定义。

- AgentManifest: agent 静态元信息(id/label/aliases/version/steps/enabled)
- Event:       SSE 事件统一 schema(总线传输的最小单位)
- Agent:       agent 实现需符合的 Protocol(manifest + async run())
- HarnessContext: agent.run 接收的运行时上下文
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Literal, Protocol, TypedDict


class StepSpec(TypedDict):
    id: str
    label: str
    estimated_seconds: int


class AgentManifest(TypedDict):
    id: str
    label: str
    aliases: list[str]
    description: str
    version: str
    steps: list[StepSpec]
    requires: list[str]
    enabled: bool


EventType = Literal[
    "thinking", "tool_start", "tool_done", "generating", "done", "error"
]


class Event(TypedDict, total=False):
    type: EventType
    agent_id: str
    agent_label: str
    step_id: str
    step_label: str
    step_index: int
    step_total: int
    delta: str
    message: str
    report_path: str


class HarnessContext(Protocol):
    workspace: Path
    session_id: str
    emit: Callable[[Event], Awaitable[None]]
    log_decision: Callable[[str, dict], Awaitable[None]]


class Agent(Protocol):
    manifest: AgentManifest

    async def run(self, *, ref, llm, ctx: HarnessContext) -> AsyncIterator[Event]: ...
