"""问股期 1 — Task 13:LLMClient 抽象基类 + 公共类型。

本模块定义 LLM 调用的统一接口与异常类型。具体实现由 Task 14
(OpenAI 兼容)与 Task 15(Anthropic 原生)填充。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import httpx

from services.system_config.channels import ChannelConfig


class LLMError(Exception):
    """统一的 LLM 调用异常(网络/4xx/5xx/超时/解析失败)。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Message:
    """会话消息(角色 + 文本)。"""

    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class CompletionResult:
    """非流式补全结果。tokens 字段在上游返回 usage 时填充。"""

    text: str
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class LLMClient(ABC):
    """LLM 调用抽象。所有实现必须支持非流式 complete + 流式 stream。"""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> CompletionResult: ...

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]: ...


class OpenAICompatibleClient(LLMClient):
    """OpenAI / DeepSeek / OpenRouter 共用实现。

    协议:`POST {base_url}/chat/completions`,Bearer 鉴权,
    流式走 SSE(`data: {...}\\n\\n` + `data: [DONE]`)。
    """

    def __init__(
        self,
        ch: ChannelConfig,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.ch = ch
        self._transport = transport

    def _payload(
        self,
        messages: list[Message],
        max_tokens: Optional[int],
        temperature: Optional[float],
        stream: bool,
    ) -> dict:
        return {
            "model": self.ch.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens or self.ch.max_tokens,
            "temperature": temperature
            if temperature is not None
            else self.ch.temperature,
            "stream": stream,
        }

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.ch.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self) -> str:
        return self.ch.base_url.rstrip("/") + "/chat/completions"

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> CompletionResult:
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout or self.ch.timeout,
        ) as cli:
            try:
                r = await cli.post(
                    self._url(),
                    headers=self._headers(),
                    json=self._payload(messages, max_tokens, temperature, stream=False),
                )
            except httpx.HTTPError as e:
                raise LLMError("NETWORK", str(e))
        if r.status_code >= 400:
            raise LLMError(f"HTTP_{r.status_code}", r.text[:500])
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return CompletionResult(
                text=text,
                tokens_in=usage.get("prompt_tokens"),
                tokens_out=usage.get("completion_tokens"),
            )
        except (KeyError, ValueError, TypeError) as e:
            raise LLMError("PARSE", f"unexpected response: {e}")

    async def stream(
        self,
        messages: list[Message],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout or self.ch.timeout,
        ) as cli:
            try:
                async with cli.stream(
                    "POST",
                    self._url(),
                    headers=self._headers(),
                    json=self._payload(messages, max_tokens, temperature, stream=True),
                ) as r:
                    if r.status_code >= 400:
                        body = await r.aread()
                        raise LLMError(
                            f"HTTP_{r.status_code}",
                            body.decode("utf-8", "ignore")[:500],
                        )
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            return
                        try:
                            evt = json.loads(payload)
                            delta = evt["choices"][0].get("delta", {}).get("content")
                            if delta:
                                yield delta
                        except (KeyError, ValueError):
                            continue
            except httpx.HTTPError as e:
                raise LLMError("NETWORK", str(e))
