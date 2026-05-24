"""问股期 1 — Task 15:AnthropicClient + build_client 工厂测试。"""

import json

import httpx
import pytest

from services.system_config.channels import ChannelConfig
from services.system_config.llm_client import (
    AnthropicClient,
    LLMError,
    Message,
    OpenAICompatibleClient,
    build_client,
)


def _ch(provider: str = "anthropic") -> ChannelConfig:
    return ChannelConfig(
        name="S",
        provider=provider,
        base_url="https://api.anthropic.com",
        api_key="sk-ant-x",
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        temperature=0.3,
        timeout=30,
    )


async def test_complete_basic():
    body = {
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 5, "output_tokens": 1},
    }
    captured: dict = {}

    def handler(req):
        captured["x_api_key"] = req.headers.get("x-api-key")
        captured["anthropic_version"] = req.headers.get("anthropic-version")
        captured["body"] = json.loads(req.content)
        captured["url"] = str(req.url)
        return httpx.Response(200, json=body)

    client = AnthropicClient(_ch(), transport=httpx.MockTransport(handler))
    r = await client.complete([Message("user", "hi")])
    assert r.text == "hello"
    assert r.tokens_in == 5
    assert r.tokens_out == 1
    assert captured["x_api_key"] == "sk-ant-x"
    assert captured["anthropic_version"]
    assert captured["body"]["model"] == "claude-3-5-sonnet-20241022"
    assert captured["url"].endswith("/v1/messages")


async def test_system_message_extracted():
    captured: dict = {}

    def handler(req):
        captured["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "ok"}], "usage": {}},
        )

    client = AnthropicClient(_ch(), transport=httpx.MockTransport(handler))
    await client.complete([Message("system", "be brief"), Message("user", "hi")])
    assert captured["body"]["system"] == "be brief"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]


async def test_stream_yields_text_deltas():
    chunks = [
        b"event: content_block_delta\n",
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hel"}}\n\n',
        b"event: content_block_delta\n",
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]

    def handler(req):
        return httpx.Response(
            200,
            content=b"".join(chunks),
            headers={"content-type": "text/event-stream"},
        )

    client = AnthropicClient(_ch(), transport=httpx.MockTransport(handler))
    out = []
    async for piece in client.stream([Message("user", "hi")]):
        out.append(piece)
    assert "".join(out) == "hello"


async def test_4xx_raises():
    client = AnthropicClient(
        _ch(),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"error": "bad key"})
        ),
    )
    with pytest.raises(LLMError) as ei:
        await client.complete([Message("user", "hi")])
    assert ei.value.code == "HTTP_401"


def test_build_client_openai_family():
    for provider in ("openai", "deepseek", "openrouter"):
        ch = ChannelConfig(
            name="X",
            provider=provider,
            base_url="https://x/v1",
            api_key="k",
            model="m",
        )
        assert isinstance(build_client(ch), OpenAICompatibleClient)


def test_build_client_anthropic():
    assert isinstance(build_client(_ch()), AnthropicClient)


def test_build_client_unknown_provider_raises():
    ch = ChannelConfig(
        name="X", provider="mystery", base_url="u", api_key="k", model="m"
    )
    with pytest.raises(LLMError) as ei:
        build_client(ch)
    assert ei.value.code == "CONFIG"
