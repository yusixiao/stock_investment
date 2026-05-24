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
        await self.sse_send(sse.thinking("加载已有分析报告作上下文..."))
        # 取 output_dir 下唯一的 *_分析报告.md
        reports = list(output_dir.glob("*_分析报告.md"))
        report_text = reports[0].read_text(encoding="utf-8") if reports else ""
        # 取最近 10 条历史(避免上下文超长)
        history = (self.repo.list_messages(session_id) or [])[-10:]
        msgs: list[Message] = [
            Message(
                "system",
                "你是一名投资研究助理,基于以下投资分析报告回答用户的追问。"
                "请在报告范围内引用,避免编造数据。\n\n<<报告>>\n"
                + report_text
                + "\n<<报告结束>>",
            ),
        ]
        for h in history:
            if h.get("role") in ("user", "assistant"):
                msgs.append(Message(h["role"], h["content"]))
        msgs.append(Message("user", message))

        client = self.llm_factory("qa_followup")
        result = await client.complete(msgs)
        self.repo.append_message(
            session_id,
            role="assistant",
            content=result.text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
        )
        await self.sse_send(sse.done(result.text, artifacts=[]))

    async def _run_full_pipeline(self, session_id: str, ref: StockRef) -> None:
        # 在 Task 24 串接三阶段流水线
        raise NotImplementedError("full_pipeline 在 Task 24 实现")
