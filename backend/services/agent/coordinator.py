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

import time

from services.agent import sse
from services.agent.pipeline.phase1_data_pack.builder import DataPackBuilder
from services.agent.pipeline.phase3_quant import run_phase3_quant
from services.agent.pipeline.phase3_valuation import run_phase3_valuation
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
        store=None,
        indicators=None,
    ):
        self.sse_send = sse_send
        self.repo = repo
        self.workspace = workspace
        self.stock_index = stock_index
        self.llm_factory = llm_factory
        # full_pipeline 阶段需要的真实数据依赖(单测可不传)
        self.store = store
        self.indicators = indicators

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
        """完整流水线:Phase 1 数据包 → Phase 3.1 量化 → Phase 3.2 估值。"""
        d = self.workspace.ensure(ref)
        # 把 output_dir 写回 session,使后续追问命中 qa_followup
        try:
            self.repo.upsert(
                session_id,
                stock_code=ref.code,
                output_dir=str(d),
            )
        except Exception:
            # MagicMock 或某些自定义 repo 可能没有 upsert,不影响主流程
            pass

        # ---------- Phase 1:数据包 ----------
        if not await self._run_phase(
            phase="phase1_data_pack",
            display_name="生成数据包",
            workdir=d,
            fn=lambda: self._build_data_pack(ref, d),
        ):
            return

        # ---------- Phase 3.1:量化 ----------
        quant_parsed: dict = {}

        async def _phase3_quant():
            nonlocal quant_parsed
            llm = self._wrap_stream_llm(self.llm_factory("phase3_quant"))

            async def _on_chunk(s: str):
                await self.sse_send(sse.generating(s))

            _, quant_parsed = await run_phase3_quant(
                workspace=d,
                llm=llm,
                on_chunk=_on_chunk,
            )

        if not await self._run_phase(
            phase="phase3_quant",
            display_name="量化分析(穿透回报率)",
            workdir=d,
            fn=_phase3_quant,
            is_async=True,
        ):
            return

        # ---------- Phase 3.2:估值与报告组装 ----------
        report_path_holder: dict = {}

        async def _phase3_val():
            llm = self._wrap_stream_llm(self.llm_factory("phase3_valuation"))

            async def _on_chunk(s: str):
                await self.sse_send(sse.generating(s))

            report_path_holder["path"] = await run_phase3_valuation(
                workspace=d,
                llm=llm,
                company_name=ref.name,
                symbol=ref.code,
                quant_results=quant_parsed,
                on_chunk=_on_chunk,
            )

        if not await self._run_phase(
            phase="phase3_valuation",
            display_name="估值与报告生成",
            workdir=d,
            fn=_phase3_val,
            is_async=True,
        ):
            return

        # ---------- 完成:done 事件 ----------
        report_path: Path = report_path_holder["path"]
        try:
            text = report_path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        await self.sse_send(
            sse.done(
                text,
                artifacts=[
                    {
                        "path": self.workspace.relpath_for_artifact(d, report_path),
                        "name": report_path.name,
                    }
                ],
            )
        )

    # ===== full_pipeline 辅助 =====

    def _build_data_pack(self, ref: StockRef, output_dir: Path) -> None:
        """同步执行 Phase 1 数据包构建。"""
        builder = DataPackBuilder(
            store=self.store,
            stock_index=self.stock_index,
            indicators=self.indicators,
        )
        builder.build(ref, output_dir)

    async def _run_phase(
        self,
        *,
        phase: str,
        display_name: str,
        workdir: Path,
        fn,
        is_async: bool = False,
    ) -> bool:
        """统一阶段编排:tool_start → mark running → 执行 → mark done/failed → tool_done。

        失败时发 error 事件并返回 False,调用方应直接 return。
        """
        await self.sse_send(sse.tool_start(phase, display_name))
        self.workspace.mark_phase(workdir, phase, status="running")
        t0 = time.time()
        try:
            if is_async:
                await fn()
            else:
                fn()
        except Exception as e:  # noqa: BLE001
            duration = time.time() - t0
            self.workspace.mark_phase(
                workdir, phase, status="failed", duration=duration, reason=str(e)
            )
            await self.sse_send(
                sse.tool_done(phase, success=False, duration=duration, message=str(e))
            )
            await self.sse_send(sse.error("PHASE_FAILED", str(e), phase=phase))
            return False
        duration = time.time() - t0
        self.workspace.mark_phase(workdir, phase, status="done", duration=duration)
        await self.sse_send(sse.tool_done(phase, success=True, duration=duration))
        return True

    def _wrap_stream_llm(self, client: LLMClient):
        """把 LLMClient(messages-based)适配成 phase3_* 期望的 StreamLLM(prompt-based)。"""

        class _Adapter:
            def __init__(self, c: LLMClient):
                self._c = c

            async def stream(self, prompt: str, **kwargs):
                async for chunk in self._c.stream([Message("user", prompt)], **kwargs):
                    yield chunk

        return _Adapter(client)
