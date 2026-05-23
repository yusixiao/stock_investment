"""Agent 路由 — 解析消息归属哪个 agent。

优先级:
  1. explicit_agent_id(用户在 UI 选了某 agent)
  2. message 中关键字命中 manifest.aliases(取 id 字典序最小)
  3. fallback 到 default_agent_id
"""

from __future__ import annotations

from . import registry


def resolve_agent(
    *,
    message: str,
    explicit_agent_id: str | None,
    default_agent_id: str,
) -> tuple[str, str]:
    """returns (agent_id, reason) where reason ∈ {'explicit', 'keyword', 'default'}"""
    if explicit_agent_id and registry.exists(explicit_agent_id):
        return explicit_agent_id, "explicit"

    msg_lower = message.lower()
    candidates: list[str] = []
    for m in registry.list_manifests():
        for alias in m.get("aliases", []):
            if alias and alias.lower() in msg_lower:
                candidates.append(m["id"])
                break
    if candidates:
        candidates.sort()
        return candidates[0], "keyword"

    if not registry.exists(default_agent_id):
        raise RuntimeError(f"default agent '{default_agent_id}' not registered")
    return default_agent_id, "default"
