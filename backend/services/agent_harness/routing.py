"""Agent 路由 — 4 层 fallback。

优先级:
  1. explicit_agent_id     (用户在 UI 选了某 agent)
  2. @mention              (消息含 @<agent_id>)
  3. keyword alias         (消息含 manifest.aliases 任一关键字)
  4. LLM router            (短消息或无 LLM 时跳过,fallback 到 default)
       - confidence ≥ 0.6 且 agent enabled → 用之
       - 否则进入 clarify 分支:返回 None + clarification_question + quick_replies

T12.6 r2 升级:
- 函数签名变为 async(LLM router 内部需要 await)
- 返回值从 (agent_id, reason) 元组改为 RouteDecision dataclass
- 新增 mention / llm / clarify 三种 reason
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import llm_router, registry

CONFIDENCE_THRESHOLD = 0.6
MIN_MESSAGE_LEN_FOR_LLM = 4

# clarify 时给 UI 显示的快速回复按钮(label + 对应 agent_id)
DEFAULT_QUICK_REPLIES = [
    {"label": "保守分析", "agent_id": "cpa_conservative"},
    {"label": "团队分析", "agent_id": "tradingagents_astock"},
]


@dataclass
class RouteDecision:
    agent_id: str | None
    reason: str  # explicit / mention / keyword / llm / clarify / default
    confidence: float = 1.0
    clarification_question: str = ""
    quick_replies: list[dict] = field(default_factory=list)


def _parse_mention(message: str) -> str | None:
    """期 1 占位:简单解析 @<agent_id>;期 2 替换为 NLP 抽取。"""
    m = re.search(r"@([a-zA-Z_][\w-]*)", message)
    return m.group(1) if m else None


async def resolve_agent(
    *,
    message: str,
    explicit_agent_id: str | None,
    default_agent_id: str,
    llm: Any = None,
) -> RouteDecision:
    # 1. explicit
    if explicit_agent_id and registry.exists(explicit_agent_id):
        return RouteDecision(explicit_agent_id, "explicit", 1.0)

    # 2. @mention
    mention = _parse_mention(message)
    if mention and registry.exists(mention):
        return RouteDecision(mention, "mention", 1.0)

    # 3. keyword alias
    matched = registry.match_alias(message)
    if matched:
        return RouteDecision(matched, "keyword", 0.9)

    # 短消息直接 default,不浪费 token
    if len(message.strip()) < MIN_MESSAGE_LEN_FOR_LLM:
        if not registry.exists(default_agent_id):
            raise RuntimeError(f"default agent '{default_agent_id}' not registered")
        return RouteDecision(default_agent_id, "default", 0.5)

    # 4. LLM router
    if llm is None:
        # 没有 LLM 可用 → 直接 default
        if not registry.exists(default_agent_id):
            raise RuntimeError(f"default agent '{default_agent_id}' not registered")
        return RouteDecision(default_agent_id, "default", 0.5)

    enabled = registry.list_enabled()
    decision = await llm_router.classify(message=message, llm=llm, agents=enabled)

    chosen_ok = (
        decision.agent_id is not None
        and registry.exists(decision.agent_id)
        and any(a["id"] == decision.agent_id for a in enabled)
    )

    if (
        not decision.needs_clarification
        and chosen_ok
        and decision.confidence >= CONFIDENCE_THRESHOLD
    ):
        return RouteDecision(decision.agent_id, "llm", decision.confidence)

    # 4b. 澄清反问
    question = (
        decision.clarification_question
        or "抱歉,我没听明白。你是想做保守分析还是团队分析?"
    )
    return RouteDecision(
        agent_id=None,
        reason="clarify",
        confidence=decision.confidence,
        clarification_question=question,
        quick_replies=list(DEFAULT_QUICK_REPLIES),
    )
