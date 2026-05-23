from services.system_config.channels import (
    ChannelConfig,
    flatten_channels,
    get_channel,
    reconstruct_channels,
)


def test_reconstruct_channels_basic():
    kv = {
        "LLM_DEEPSEEK_PROVIDER": "deepseek",
        "LLM_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "LLM_DEEPSEEK_API_KEY": "sk-x",
        "LLM_DEEPSEEK_MODEL": "deepseek-chat",
        "LLM_DEEPSEEK_MAX_TOKENS": "8192",
        "LLM_DEEPSEEK_TEMPERATURE": "0.3",
        "LLM_DEEPSEEK_TIMEOUT": "120",
    }
    chans = reconstruct_channels(kv)
    assert len(chans) == 1
    c = chans[0]
    assert c.name == "DEEPSEEK"
    assert c.provider == "deepseek"
    assert c.api_key == "sk-x"
    assert c.max_tokens == 8192
    assert c.temperature == 0.3
    assert c.timeout == 120


def test_reconstruct_multiple_sorted():
    kv = {
        "LLM_B_PROVIDER": "anthropic",
        "LLM_B_API_KEY": "k2",
        "LLM_B_MODEL": "claude",
        "LLM_B_BASE_URL": "https://y",
        "LLM_A_PROVIDER": "openai",
        "LLM_A_API_KEY": "k1",
        "LLM_A_MODEL": "gpt-4o",
        "LLM_A_BASE_URL": "https://x",
    }
    chans = reconstruct_channels(kv)
    assert [c.name for c in chans] == ["A", "B"]


def test_flatten_roundtrip():
    c = ChannelConfig(
        name="X",
        provider="openai",
        base_url="https://x",
        api_key="k",
        model="gpt-4",
        max_tokens=4096,
        temperature=0.5,
        timeout=60,
    )
    kv = flatten_channels([c])
    chans2 = reconstruct_channels(kv)
    assert chans2[0] == c


def test_get_channel_by_name():
    kv = {
        "LLM_X_PROVIDER": "openai",
        "LLM_X_API_KEY": "k",
        "LLM_X_MODEL": "m",
        "LLM_X_BASE_URL": "u",
    }
    c = get_channel(kv, "X")
    assert c is not None
    assert c.name == "X"


def test_get_channel_missing_returns_none():
    assert get_channel({}, "X") is None


def test_reconstruct_ignores_route_keys():
    kv = {
        "LLM_DEFAULT_CHANNEL": "DEEPSEEK",
        "LLM_X_PROVIDER": "openai",
        "LLM_X_API_KEY": "k",
        "LLM_X_MODEL": "m",
        "LLM_X_BASE_URL": "u",
    }
    chans = reconstruct_channels(kv)
    assert [c.name for c in chans] == ["X"]
