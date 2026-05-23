"""LLM 意图路由 — 第 4 层 fallback,在 explicit/keyword 都不命中时通过 LLM 选 agent。

调用 `llm.complete_json(system, user, timeout)` 拿严格 JSON,解析为 RouterDecision。
任何异常(超时 / 解析失败 / LLM 抛错)都降级为 needs_clarification=True。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """你是一个意图路由器。根据用户消息,从下面的 agents 中选择最合适的一个。

可选 agents:
{agents_json}

每个 agent 的 description 与 aliases 是判断依据。

输出严格 JSON,无任何额外文字:
{{
  "agent_id": "<agent_id 或 null 表示无法判断>",
  "confidence": <0.0-1.0 的浮点数>,
  "reason": "<一句话说明为什么选这个 agent>",
  "needs_clarification": <true/false>,
  "clarification_question": "<若 needs_clarification=true,反问用户的话;否则空串>"
}}

规则:
- confidence < 0.6 时,设 needs_clarification=true 并写一句反问。
- 反问要列出可选项(用 agents 的 label),例如「你是想做保守分析还是团队分析?」
- 不要选 enabled=false 的 agent(候选池已过滤)。
"""

ROUTER_USER_PROMPT = "用户消息:\n{message}"

DEFAULT_CLARIFICATION = (
    "抱歉,我没听明白。你是想做保守分析(穿透回报率精算)还是团队分析(多角色辩论)?"
)
ROUTER_TIMEOUT_SEC = 10.0


class RouterDecision(BaseModel):
    agent_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    needs_clarification: bool
    clarification_question: str = ""


def _build_system_prompt(agents: list[dict]) -> str:
    payload = [
        {
            "id": a["id"],
            "label": a["label"],
            "description": a["description"],
            "aliases": a["aliases"],
        }
        for a in agents
    ]
    return ROUTER_SYSTEM_PROMPT.format(
        agents_json=json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _fallback(reason: str) -> RouterDecision:
    return RouterDecision(
        agent_id=None,
        confidence=0.0,
        reason=reason,
        needs_clarification=True,
        clarification_question=DEFAULT_CLARIFICATION,
    )


async def classify(*, message: str, llm: Any, agents: list[dict]) -> RouterDecision:
    """非流式 LLM 调用,JSON 输出 → RouterDecision。失败时降级澄清。"""
    if not agents:
        return _fallback("无可用 agent")
    system = _build_system_prompt(agents)
    user = ROUTER_USER_PROMPT.format(message=message)
    try:
        raw = await asyncio.wait_for(
            llm.complete_json(system=system, user=user, timeout=ROUTER_TIMEOUT_SEC),
            timeout=ROUTER_TIMEOUT_SEC + 1.0,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "LLM router timeout (>%.1fs); fallback to clarify", ROUTER_TIMEOUT_SEC
        )
        return _fallback("LLM 路由超时")
    except Exception as e:
        logger.warning("LLM router exception: %s; fallback to clarify", e)
        return _fallback("LLM 路由异常")

    try:
        return RouterDecision.model_validate_json(raw)
    except ValidationError as e:
        logger.warning("LLM router JSON 解析失败: %s; raw=%s", e, str(raw)[:200])
        return _fallback("LLM 路由解析失败")
    except Exception as e:
        logger.warning("LLM router unexpected error: %s", e)
        return _fallback("LLM 路由解析失败")
