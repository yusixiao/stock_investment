"""field_schema:9 字段 schema 定义 + masked items 渲染。"""

from __future__ import annotations

from services.system_config.field_schema import (
    MASK_TOKEN,
    build_categories,
    build_items,
    iter_field_schemas,
)


def test_iter_field_schemas_covers_all_9_keys():
    keys = {f["key"] for f in iter_field_schemas()}
    assert keys == {
        "LLM_OPENROUTER_PROVIDER",
        "LLM_OPENROUTER_BASE_URL",
        "LLM_OPENROUTER_API_KEY",
        "LLM_OPENROUTER_MODEL",
        "LLM_OPENROUTER_MAX_TOKENS",
        "LLM_OPENROUTER_TEMPERATURE",
        "LLM_OPENROUTER_TIMEOUT",
        "LLM_DEFAULT_CHANNEL",
        "TAVILY_API_KEY",
    }


def test_field_schema_categories():
    by_key = {f["key"]: f for f in iter_field_schemas()}
    # 8 个 LLM 字段在 ai_model
    assert by_key["LLM_OPENROUTER_API_KEY"]["category"] == "ai_model"
    assert by_key["LLM_DEFAULT_CHANNEL"]["category"] == "ai_model"
    # TAVILY 在 data_source
    assert by_key["TAVILY_API_KEY"]["category"] == "data_source"


def test_sensitive_fields_marked():
    by_key = {f["key"]: f for f in iter_field_schemas()}
    assert by_key["LLM_OPENROUTER_API_KEY"]["is_sensitive"] is True
    assert by_key["TAVILY_API_KEY"]["is_sensitive"] is True
    assert by_key["LLM_OPENROUTER_BASE_URL"]["is_sensitive"] is False
    assert by_key["LLM_OPENROUTER_MAX_TOKENS"]["is_sensitive"] is False


def test_field_data_types():
    by_key = {f["key"]: f for f in iter_field_schemas()}
    assert by_key["LLM_OPENROUTER_MAX_TOKENS"]["data_type"] == "integer"
    assert by_key["LLM_OPENROUTER_TIMEOUT"]["data_type"] == "integer"
    assert by_key["LLM_OPENROUTER_TEMPERATURE"]["data_type"] == "number"
    assert by_key["LLM_OPENROUTER_API_KEY"]["data_type"] == "string"


def test_ui_controls():
    by_key = {f["key"]: f for f in iter_field_schemas()}
    assert by_key["LLM_OPENROUTER_API_KEY"]["ui_control"] == "password"
    assert by_key["TAVILY_API_KEY"]["ui_control"] == "password"
    assert by_key["LLM_OPENROUTER_MAX_TOKENS"]["ui_control"] == "number"
    assert by_key["LLM_OPENROUTER_TEMPERATURE"]["ui_control"] == "number"


def test_build_categories_groups_fields():
    cats = build_categories()
    by_cat = {c["category"]: c for c in cats}
    assert "ai_model" in by_cat
    assert "data_source" in by_cat
    ai = by_cat["ai_model"]
    assert {f["key"] for f in ai["fields"]} >= {
        "LLM_OPENROUTER_API_KEY",
        "LLM_DEFAULT_CHANNEL",
    }
    ds = by_cat["data_source"]
    assert any(f["key"] == "TAVILY_API_KEY" for f in ds["fields"])


def test_build_items_masks_sensitive_values():
    kv = {
        "LLM_OPENROUTER_API_KEY": "sk-or-v1-secret",
        "LLM_OPENROUTER_MODEL": "gpt-oss-120b",
        "TAVILY_API_KEY": "tvly-secret",
    }
    items = build_items(kv)
    by_key = {it["key"]: it for it in items}
    # 敏感字段被遮掩,但 rawValueExists=True
    assert by_key["LLM_OPENROUTER_API_KEY"]["value"] == MASK_TOKEN
    assert by_key["LLM_OPENROUTER_API_KEY"]["is_masked"] is True
    assert by_key["LLM_OPENROUTER_API_KEY"]["raw_value_exists"] is True
    assert by_key["TAVILY_API_KEY"]["value"] == MASK_TOKEN
    assert by_key["TAVILY_API_KEY"]["is_masked"] is True
    # 非敏感字段不遮掩
    assert by_key["LLM_OPENROUTER_MODEL"]["value"] == "gpt-oss-120b"
    assert by_key["LLM_OPENROUTER_MODEL"]["is_masked"] is False


def test_build_items_handles_empty_sensitive():
    kv = {"LLM_OPENROUTER_API_KEY": ""}
    items = build_items(kv)
    by_key = {it["key"]: it for it in items}
    # 空敏感值不遮掩,rawValueExists=False
    assert by_key["LLM_OPENROUTER_API_KEY"]["value"] == ""
    assert by_key["LLM_OPENROUTER_API_KEY"]["is_masked"] is False
    assert by_key["LLM_OPENROUTER_API_KEY"]["raw_value_exists"] is False


def test_build_items_includes_all_schema_keys_even_if_kv_missing():
    """yaml 里没写的 key 也应作为 item 列出(value=""),让前端能看到完整字段。"""
    kv = {"LLM_OPENROUTER_API_KEY": "sk-x"}
    items = build_items(kv)
    keys = {it["key"] for it in items}
    # 9 个 schema 字段都应在
    assert len(keys) == 9
    by_key = {it["key"]: it for it in items}
    assert by_key["LLM_OPENROUTER_BASE_URL"]["value"] == ""
    assert by_key["LLM_OPENROUTER_BASE_URL"]["raw_value_exists"] is False


def test_build_items_includes_unknown_keys_as_uncategorized():
    """yaml 里有但 schema 没声明的字段,以 uncategorized 形式透出。"""
    kv = {"LLM_OPENROUTER_API_KEY": "sk", "MYSTERY_KEY": "v"}
    items = build_items(kv)
    by_key = {it["key"]: it for it in items}
    assert "MYSTERY_KEY" in by_key
    assert by_key["MYSTERY_KEY"]["value"] == "v"
    assert by_key["MYSTERY_KEY"].get("schema", {}).get("category") == "uncategorized"
