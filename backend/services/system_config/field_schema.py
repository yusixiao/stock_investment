"""问股期 1 — 系统配置字段 schema 定义。

只描述当前 yaml 实际使用的 9 个字段:
- 8 个 LLM OpenRouter channel + 全局路由 → ai_model
- 1 个 Tavily 搜索 key → data_source

设计要点:
- schema 是单一可信源(SSOT),前后端共享
- 敏感字段(API key)在 GET /system/config 时被遮掩为 MASK_TOKEN(******)
- PUT 时若收到 MASK_TOKEN 表示「保留原值」,不实际写入
- 未声明的 yaml key 以 uncategorized 形式透出,允许手工添加未来的字段
"""

from __future__ import annotations

from typing import Any, Iterable

MASK_TOKEN = "******"


# ===== 字段 schema 定义(显式列出,便于前端 i18n 对位)=====

_FIELDS: list[dict[str, Any]] = [
    # ----- ai_model:OpenRouter channel -----
    {
        "key": "LLM_OPENROUTER_PROVIDER",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": True,
        "is_editable": True,
        "default_value": "openrouter",
        "display_order": 10,
    },
    {
        "key": "LLM_OPENROUTER_BASE_URL",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": True,
        "is_editable": True,
        "default_value": "https://openrouter.ai/api/v1",
        "display_order": 11,
    },
    {
        "key": "LLM_OPENROUTER_API_KEY",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": True,
        "is_editable": True,
        "default_value": "",
        "display_order": 12,
    },
    {
        "key": "LLM_OPENROUTER_MODEL",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": True,
        "is_editable": True,
        "default_value": "openai/gpt-oss-120b:free",
        "display_order": 13,
    },
    {
        "key": "LLM_OPENROUTER_MAX_TOKENS",
        "category": "ai_model",
        "data_type": "integer",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "8000",
        "display_order": 14,
        "validation": {"min": 1, "max": 200000},
    },
    {
        "key": "LLM_OPENROUTER_TEMPERATURE",
        "category": "ai_model",
        "data_type": "number",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "0.3",
        "display_order": 15,
        "validation": {"min": 0, "max": 2},
    },
    {
        "key": "LLM_OPENROUTER_TIMEOUT",
        "category": "ai_model",
        "data_type": "integer",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "180",
        "display_order": 16,
        "validation": {"min": 1, "max": 3600},
    },
    {
        "key": "LLM_DEFAULT_CHANNEL",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": True,
        "is_editable": True,
        "default_value": "OPENROUTER",
        "display_order": 1,  # 全局路由排在最前
    },
    # ----- data_source:Tavily 搜索 -----
    {
        "key": "TAVILY_API_KEY",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": "",
        "display_order": 100,
    },
]

_BY_KEY = {f["key"]: f for f in _FIELDS}


_CATEGORY_TITLES = {
    "ai_model": "AI 模型",
    "data_source": "数据源",
    "uncategorized": "其他",
}

_CATEGORY_ORDER = {
    "ai_model": 10,
    "data_source": 20,
    "uncategorized": 999,
}


def iter_field_schemas() -> list[dict[str, Any]]:
    """返回 schema 列表(每个元素含默认值 options=[]、validation={} 兜底)。"""
    out: list[dict[str, Any]] = []
    for raw in _FIELDS:
        f = dict(raw)
        f.setdefault("options", [])
        f.setdefault("validation", {})
        out.append(f)
    return out


def get_field_schema(key: str) -> dict[str, Any] | None:
    raw = _BY_KEY.get(key)
    if raw is None:
        return None
    f = dict(raw)
    f.setdefault("options", [])
    f.setdefault("validation", {})
    return f


def is_sensitive(key: str) -> bool:
    f = _BY_KEY.get(key)
    return bool(f and f.get("is_sensitive"))


def build_categories() -> list[dict[str, Any]]:
    """聚合 schema 字段为 category 列表(给前端 SettingsCategoryNav 用)。"""
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for f in iter_field_schemas():
        by_cat.setdefault(f["category"], []).append(f)
    cats: list[dict[str, Any]] = []
    for cat, fields in by_cat.items():
        cats.append(
            {
                "category": cat,
                "title": _CATEGORY_TITLES.get(cat, cat),
                "display_order": _CATEGORY_ORDER.get(cat, 500),
                "fields": sorted(fields, key=lambda f: f.get("display_order", 999)),
            }
        )
    cats.sort(key=lambda c: c["display_order"])
    return cats


def build_items(kv: dict[str, str]) -> list[dict[str, Any]]:
    """根据 yaml KV 渲染前端展示用的 items 列表。

    - schema 声明的 key 都会出现(yaml 里没写的 value="")
    - 敏感字段非空值会被遮掩为 MASK_TOKEN
    - yaml 里 schema 未声明的 key 以 uncategorized 透出
    """
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for f in iter_field_schemas():
        key = f["key"]
        seen.add(key)
        raw = kv.get(key, "")
        sensitive = bool(f.get("is_sensitive"))
        masked = sensitive and raw != ""
        items.append(
            {
                "key": key,
                "value": MASK_TOKEN if masked else raw,
                "raw_value_exists": raw != "",
                "is_masked": masked,
                "schema": f,
            }
        )

    # yaml 里有但 schema 未声明的额外 key
    for key, raw in kv.items():
        if key in seen:
            continue
        items.append(
            {
                "key": key,
                "value": raw,
                "raw_value_exists": raw != "",
                "is_masked": False,
                "schema": {
                    "key": key,
                    "category": "uncategorized",
                    "data_type": "string",
                    "ui_control": "text",
                    "is_sensitive": False,
                    "is_required": False,
                    "is_editable": True,
                    "options": [],
                    "validation": {},
                    "display_order": 999,
                },
            }
        )

    return items


def unmask_for_save(
    new_kv: dict[str, str], existing_kv: dict[str, str]
) -> dict[str, str]:
    """PUT 时把客户端传回的 MASK_TOKEN 还原为原值(表示「保留」)。

    - 敏感字段且 value == MASK_TOKEN → 用 existing 值
    - 其他场景:原样保留(包括用户主动清空敏感字段)
    """
    out: dict[str, str] = {}
    for k, v in new_kv.items():
        if v == MASK_TOKEN and is_sensitive(k):
            out[k] = existing_kv.get(k, "")
        else:
            out[k] = v
    return out


def keys_with_mask(new_kv: dict[str, str]) -> Iterable[str]:
    """返回 PUT 载荷里被 MASK_TOKEN 标记为「保留」的敏感 key 列表。"""
    return [k for k, v in new_kv.items() if v == MASK_TOKEN and is_sensitive(k)]
