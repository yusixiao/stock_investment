import pytest

from services.system_config.schema import (
    ConfigError,
    KEY_PATTERN_LLM,
    parse_llm_key,
    validate_kv,
)


def test_parse_llm_key_valid():
    assert parse_llm_key("LLM_DEEPSEEK_API_KEY") == ("DEEPSEEK", "API_KEY")
    assert parse_llm_key("LLM_GPT_4O_MAX_TOKENS") == ("GPT_4O", "MAX_TOKENS")


def test_parse_llm_key_invalid_returns_none():
    assert parse_llm_key("FOO") is None
    assert parse_llm_key("LLM_") is None


def test_parse_llm_key_route_keys_excluded():
    # Route keys 不是 channel 字段
    assert parse_llm_key("LLM_DEFAULT_CHANNEL") is None


def test_validate_kv_accepts_known_fields():
    kv = {
        "LLM_DEEPSEEK_PROVIDER": "deepseek",
        "LLM_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "LLM_DEEPSEEK_API_KEY": "sk-x",
        "LLM_DEEPSEEK_MODEL": "deepseek-chat",
        "LLM_DEFAULT_CHANNEL": "DEEPSEEK",
    }
    validate_kv(kv)  # no raise


def test_validate_kv_rejects_unknown_provider():
    with pytest.raises(ConfigError):
        validate_kv({"LLM_X_PROVIDER": "weird-vendor"})


def test_validate_kv_default_channel_must_exist():
    with pytest.raises(ConfigError):
        validate_kv({"LLM_DEFAULT_CHANNEL": "NONEXIST"})


def test_validate_kv_ignores_non_llm_keys():
    validate_kv({"FOO": "bar", "BAZ": "qux"})  # no raise


def test_key_pattern_constant_exported():
    assert KEY_PATTERN_LLM.match("LLM_FOO_API_KEY")
