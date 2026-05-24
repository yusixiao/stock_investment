"""问股期 1 — Task 16:phase → LLM channel 名称解析。

业务流程中各 phase(三级量化分析、估值、追问、闲聊)可在系统配置里
绑定不同的 LLM channel,以兼顾成本与质量。

解析顺序:
1. 若 phase 在 PHASE_TO_ROUTE_KEY 内,且 KV 中存在对应 LLM_ROUTE_* 项 → 用之
2. 否则回落到 LLM_DEFAULT_CHANNEL
3. 都没有 → 抛 RoutingError
"""

from __future__ import annotations


class RoutingError(ValueError):
    """无法为 phase 解析 channel 时抛出。"""


# 业务 phase 名 → 系统配置 KV 中的路由键
PHASE_TO_ROUTE_KEY: dict[str, str] = {
    "phase3_quantitative": "LLM_ROUTE_PHASE3_QUANT",
    "phase3_valuation": "LLM_ROUTE_PHASE3_VALUATION",
    "qa_followup": "LLM_ROUTE_QA_FOLLOWUP",
    "chitchat": "LLM_ROUTE_CHITCHAT",
}


def resolve_channel_name(kv: dict, phase: str) -> str:
    """解析 phase 应使用的 channel 名(对应 ChannelConfig.name)。"""
    route_key = PHASE_TO_ROUTE_KEY.get(phase)
    if route_key:
        val = kv.get(route_key)
        if val:
            return val
    default = kv.get("LLM_DEFAULT_CHANNEL")
    if default:
        return default
    raise RoutingError(
        f"无法为 phase={phase!r} 选择 channel:LLM_DEFAULT_CHANNEL 未配置"
    )
