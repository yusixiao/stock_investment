"""CPA 问股 agent — 个股深度分析(三阶段流水线)。

执行流程:
  Phase 1 数据包 → Phase 3.1 量化(穿透回报率) → Phase 3.2 估值与最终报告

由 Coordinator 在路由命中股票码时调用 `CpaAgent(...).run(session_id, ref)`,
统一通过注入的 sse_send 发出 SSE 事件。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from services.agent.agents.cpa.pipeline.phase1_data_pack.builder import DataPackBuilder
from services.agent.agents.cpa.pipeline.phase3_quant import run_phase3_quant
from services.agent.agents.cpa.pipeline.phase3_valuation import run_phase3_valuation
from services.agent.core import sse
from services.agent.core.symbol import StockRef
from services.system_config.llm_client import LLMClient, Message

SseSend = Callable[[dict], Awaitable[None]]


class CpaAgent:
    """CPA 问股 agent:执行三阶段流水线 + 统一 phase 编排 + SSE 事件流。"""

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
        tavily=None,
    ):
        self.sse_send = sse_send
        self.repo = repo
        self.workspace = workspace
        self.stock_index = stock_index
        self.llm_factory = llm_factory
        # full_pipeline 阶段需要的真实数据依赖(单测可不传)
        self.store = store
        self.indicators = indicators
        # 可选 Tavily web search(§8 行业 / §10 ESG);无 key 自动降级
        self.tavily = tavily

    async def run(self, session_id: str, ref: StockRef) -> None:
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
        artifacts = [
            {
                "path": self.workspace.relpath_for_artifact(d, report_path),
                "name": report_path.name,
            }
        ]
        # 持久化助手消息(含报告 artifacts),否则切回历史会话只剩用户消息、报告卡片丢失
        try:
            self.repo.append_message(
                session_id,
                role="assistant",
                content=text,
                artifacts=artifacts,
            )
        except Exception:
            # MagicMock 或自定义 repo 异常不影响 SSE 完成事件
            pass
        await self.sse_send(sse.done(text, artifacts=artifacts))

    # ===== 内部辅助 =====

    def _build_data_pack(self, ref: StockRef, output_dir: Path) -> None:
        """同步执行 Phase 1 数据包构建。"""
        builder = DataPackBuilder(
            store=self.store,
            stock_index=self.stock_index,
            indicators=self.indicators,
            tavily=self.tavily,
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
