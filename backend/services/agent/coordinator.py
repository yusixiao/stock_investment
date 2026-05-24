"""问股期 1 — Task 17/19/24:Coordinator 三分支编排器。

期 1 三分支:
- chitchat:无股票上下文 + 无已完成报告 → 单次 LLM 闲聊
- qa_followup:已存在完整报告 → 基于报告的追问(Task 19/23)
- full_pipeline:识别到股票码 → 走完整三阶段(Task 24)

任何异常都通过 sse.error 事件输出,不向上抛。
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable, Optional

from services.agent import sse
from services.agent.symbol import StockRef, extract
from services.system_config.llm_client import LLMClient, LLMError, Message

SseSend = Callable[[dict], Awaitable[None]]


class Coordinator:
    """Coordinator 负责按上下文路由到合适分支并发出 SSE 事件流。"""

    def __init__(
        self,
        *,
        sse_send: SseSend,
        repo,
        workspace,
        stock_index,
        llm_factory: Callable[[str], LLMClient],
    ):
        self.sse_send = sse_send
        self.repo = repo
        self.workspace = workspace
        self.stock_index = stock_index
        self.llm_factory = llm_factory

    async def run(
        self,
        *,
        session_id: str,
        message: str,
        context: Optional[dict],
    ) -> None:
        try:
            session = self.repo.get(session_id) or {}
            output_dir = session.get("output_dir")
            if output_dir and self._has_completed_report(Path(output_dir)):
                return await self._run_qa_followup(
                    session_id, message, Path(output_dir)
                )
            ref = extract(message, context, stock_index=self.stock_index)
            if ref is not None:
                return await self._run_full_pipeline(session_id, ref)
            return await self._run_chitchat(session_id, message)
        except LLMError as e:
            await self.sse_send(sse.error(e.code, e.message))
        except Exception as e:  # noqa: BLE001 — 兜底防漏
            await self.sse_send(sse.error("INTERNAL", str(e)))

    # ===== 内部 =====

    def _has_completed_report(self, d: Path) -> bool:
        try:
            meta = self.workspace.read_meta(d)
        except Exception:
            return False
        return (
            meta.get("phases", {}).get("phase3_valuation", {}).get("status") == "done"
        )

    async def _run_chitchat(self, session_id: str, message: str) -> None:
        await self.sse_send(sse.thinking("闲聊模式..."))
        client = self.llm_factory("chitchat")
        result = await client.complete(
            [
                Message(
                    "system", "你是一名简洁友好的中文 AI 助手,回答问题并保持中立。"
                ),
                Message("user", message),
            ]
        )
        self.repo.append_message(
            session_id,
            role="assistant",
            content=result.text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
        )
        await self.sse_send(sse.done(result.text, artifacts=[]))

    async def _run_qa_followup(
        self, session_id: str, message: str, output_dir: Path
    ) -> None:
        # 在 Task 19 实现完整报告答疑逻辑
        raise NotImplementedError("qa_followup 在 Task 19 实现")

    async def _run_full_pipeline(self, session_id: str, ref: StockRef) -> None:
        # 在 Task 24 串接三阶段流水线
        raise NotImplementedError("full_pipeline 在 Task 24 实现")
