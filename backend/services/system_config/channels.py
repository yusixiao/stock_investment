"""扁平 KV ↔ ChannelConfig 互转。

KV 形如 LLM_<NAME>_<FIELD>=value;ChannelConfig 是聚合视图,便于业务代码使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.system_config.schema import parse_llm_key


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    provider: str
    base_url: str
    api_key: str
    model: str
    max_tokens: int = 8192
    temperature: float = 0.3
    timeout: int = 120


# field key (in flat KV) -> (dataclass attr, type converter)
_FIELD_MAP = {
    "PROVIDER": ("provider", str),
    "BASE_URL": ("base_url", str),
    "API_KEY": ("api_key", str),
    "MODEL": ("model", str),
    "MAX_TOKENS": ("max_tokens", int),
    "TEMPERATURE": ("temperature", float),
    "TIMEOUT": ("timeout", int),
}


def reconstruct_channels(kv: dict) -> list[ChannelConfig]:
    buckets: dict[str, dict] = {}
    for k, v in kv.items():
        parsed = parse_llm_key(k)
        if not parsed:
            continue
        name, field = parsed
        py_field, conv = _FIELD_MAP[field]
        try:
            buckets.setdefault(name, {})[py_field] = conv(v) if v != "" else None
        except (ValueError, TypeError):
            # 转换失败的字段忽略,后续以默认值兜底
            continue

    out: list[ChannelConfig] = []
    for name, fields in buckets.items():
        try:
            out.append(
                ChannelConfig(
                    name=name,
                    provider=fields.get("provider") or "",
                    base_url=fields.get("base_url") or "",
                    api_key=fields.get("api_key") or "",
                    model=fields.get("model") or "",
                    max_tokens=fields.get("max_tokens") or 8192,
                    temperature=(
                        fields.get("temperature")
                        if fields.get("temperature") is not None
                        else 0.3
                    ),
                    timeout=fields.get("timeout") or 120,
                )
            )
        except Exception:
            continue
    return sorted(out, key=lambda c: c.name)


def flatten_channels(channels: list[ChannelConfig]) -> dict[str, str]:
    kv: dict[str, str] = {}
    for c in channels:
        kv[f"LLM_{c.name}_PROVIDER"] = c.provider
        kv[f"LLM_{c.name}_BASE_URL"] = c.base_url
        kv[f"LLM_{c.name}_API_KEY"] = c.api_key
        kv[f"LLM_{c.name}_MODEL"] = c.model
        kv[f"LLM_{c.name}_MAX_TOKENS"] = str(c.max_tokens)
        kv[f"LLM_{c.name}_TEMPERATURE"] = str(c.temperature)
        kv[f"LLM_{c.name}_TIMEOUT"] = str(c.timeout)
    return kv


def get_channel(kv: dict, name: str) -> Optional[ChannelConfig]:
    for c in reconstruct_channels(kv):
        if c.name == name:
            return c
    return None
