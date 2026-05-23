"""Agent registry:进程内单例 dict,记录 manifest + factory。

启动时由 agent 模块 import 触发 register;dispatcher 通过 get_agent() 实例化。
"""

from __future__ import annotations

from typing import Any, Callable

from .protocol import AgentManifest

_ENTRIES: dict[str, dict[str, Any]] = {}


def register(manifest: AgentManifest, agent_factory: Callable[[], Any]) -> None:
    aid = manifest["id"]
    if aid in _ENTRIES:
        raise ValueError(f"agent {aid} already registered")
    _ENTRIES[aid] = {"manifest": manifest, "factory": agent_factory}


def exists(agent_id: str) -> bool:
    return agent_id in _ENTRIES


def get_manifest(agent_id: str) -> AgentManifest:
    if agent_id not in _ENTRIES:
        raise KeyError(f"unknown agent: {agent_id}")
    return _ENTRIES[agent_id]["manifest"]


def get_agent(agent_id: str):
    if agent_id not in _ENTRIES:
        raise KeyError(f"unknown agent: {agent_id}")
    return _ENTRIES[agent_id]["factory"]()


def list_manifests(*, only_enabled: bool = False) -> list[AgentManifest]:
    out = [e["manifest"] for e in _ENTRIES.values()]
    if only_enabled:
        out = [m for m in out if m.get("enabled", True)]
    return sorted(out, key=lambda m: m["id"])


def _clear() -> None:
    """test only"""
    _ENTRIES.clear()
