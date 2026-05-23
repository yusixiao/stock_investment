"""问股期 1 — Task 13:LLMClient 抽象基类 + 公共类型。

本模块定义 LLM 调用的统一接口与异常类型。具体实现由 Task 14
(OpenAI 兼容)与 Task 15(Anthropic 原生)填充。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


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
