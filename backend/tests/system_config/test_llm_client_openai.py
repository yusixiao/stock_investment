"""问股期 1 — Task 13/14:LLMClient 抽象基类 + OpenAICompatibleClient 测试。"""

import json

import httpx
import pytest

from services.system_config.channels import ChannelConfig
from services.system_config.llm_client import (
    LLMClient,
    LLMError,
    Message,
    OpenAICompatibleClient,
)


# ===== Task 13 =====


def test_message_dataclass():
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"


def test_llm_error_is_exception():
    assert issubclass(LLMError, Exception)


def test_llm_error_carries_code():
    e = LLMError("HTTP_401", "bad key")
    assert e.code == "HTTP_401"
    assert e.message == "bad key"
    assert "HTTP_401" in str(e)


def test_client_is_abstract():
    import inspect

    assert inspect.isabstract(LLMClient)


# ===== Task 14 =====


def _ch(provider: str = "openai") -> ChannelConfig:
    return ChannelConfig(
        name="X",
        provider=provider,
        base_url="https://api.x.com/v1",
        api_key="sk-test",
        model="gpt-4o-mini",
        max_tokens=1024,
        temperature=0.3,
        timeout=30,
    )


async def test_complete_returns_text():
    body = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    client = OpenAICompatibleClient(_ch(), transport=transport)
    r = await client.complete([Message("user", "hi")])
    assert r.text == "hello"
    assert r.tokens_in == 5
    assert r.tokens_out == 1


async def test_complete_4xx_raises_llm_error():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(401, json={"error": "bad key"})
    )
    client = OpenAICompatibleClient(_ch(), transport=transport)
    with pytest.raises(LLMError) as ei:
        await client.complete([Message("user", "hi")])
    assert ei.value.code == "HTTP_401"


async def test_stream_yields_deltas():
    chunks = [
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    def handler(req):
        return httpx.Response(
            200,
            content=b"".join(chunks),
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    client = OpenAICompatibleClient(_ch(), transport=transport)
    out = []
    async for piece in client.stream([Message("user", "hi")]):
        out.append(piece)
    assert "".join(out) == "hello"


async def test_request_includes_authorization_header_and_model():
    captured: dict = {}

    def handler(req):
        captured["auth"] = req.headers.get("authorization")
        captured["model"] = json.loads(req.content)["model"]
        captured["url"] = str(req.url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}}], "usage": {}},
        )

    client = OpenAICompatibleClient(_ch(), transport=httpx.MockTransport(handler))
    await client.complete([Message("user", "hi")])
    assert captured["auth"] == "Bearer sk-test"
    assert captured["model"] == "gpt-4o-mini"
    assert captured["url"].endswith("/chat/completions")


async def test_network_error_raises_llm_error():
    def handler(req):
        raise httpx.ConnectError("boom")

    client = OpenAICompatibleClient(_ch(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError) as ei:
        await client.complete([Message("user", "hi")])
    assert ei.value.code == "NETWORK"


async def test_parse_error_raises_llm_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"weird": 1}))
    client = OpenAICompatibleClient(_ch(), transport=transport)
    with pytest.raises(LLMError) as ei:
        await client.complete([Message("user", "hi")])
    assert ei.value.code == "PARSE"
