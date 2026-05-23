"""扁平 KV 配置的命名规则与校验。

LLM channel 字段:LLM_<CHANNEL>_<FIELD>,例如 LLM_DEEPSEEK_API_KEY。
路由键(单独):LLM_DEFAULT_CHANNEL / LLM_ROUTE_*。
"""

from __future__ import annotations

import re
from typing import Optional


class ConfigError(ValueError):
    pass


KEY_PATTERN_LLM = re.compile(
    r"^LLM_([A-Z][A-Z0-9_]*?)_(PROVIDER|BASE_URL|API_KEY|MODEL|MAX_TOKENS|TEMPERATURE|TIMEOUT)$"
)
ALLOWED_PROVIDERS = {"openai", "anthropic", "openrouter", "deepseek"}
ROUTE_KEYS = {
    "LLM_DEFAULT_CHANNEL",
    "LLM_ROUTE_PHASE3_QUANT",
    "LLM_ROUTE_PHASE3_VALUATION",
    "LLM_ROUTE_QA_FOLLOWUP",
    "LLM_ROUTE_CHITCHAT",
}


def parse_llm_key(key: str) -> Optional[tuple[str, str]]:
    """LLM_DEEPSEEK_API_KEY -> (DEEPSEEK, API_KEY);路由键 / 非 LLM 键返回 None"""
    if not key.startswith("LLM_") or key in ROUTE_KEYS:
        return None
    m = KEY_PATTERN_LLM.match(key)
    return (m.group(1), m.group(2)) if m else None


def list_channels(kv: dict) -> set[str]:
    names: set[str] = set()
    for k in kv:
        parsed = parse_llm_key(k)
        if parsed:
            names.add(parsed[0])
    return names


def validate_kv(kv: dict) -> None:
    channels = list_channels(kv)
    for k, v in kv.items():
        if not k.startswith("LLM_"):
            continue
        if k in ROUTE_KEYS:
            # 路由值必须指向已声明的 channel(空值放行)
            if v and v not in channels:
                raise ConfigError(
                    f"{k}={v} 指向的 channel 不存在;已知 channels={channels}"
                )
            continue
        parsed = parse_llm_key(k)
        if not parsed:
            raise ConfigError(f"未知的 LLM 配置键:{k}")
        _, field = parsed
        if field == "PROVIDER" and v not in ALLOWED_PROVIDERS:
            raise ConfigError(f"{k} provider 必须是 {ALLOWED_PROVIDERS},得到 {v!r}")
