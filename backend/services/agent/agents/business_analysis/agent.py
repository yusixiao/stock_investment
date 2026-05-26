"""BusinessAnalysisAgent — 团队定性分析 agent(用户入口)。

执行流程:
  1. 外层 tool_start("business_analysis", "定性分析(6 维度)")
  2. 调 run_qualitative,内部事件映射成 SSE:
       cache_hit       → thinking + 跳过子事件
       dimension_start → tool_start(d{n}, title)
       dimension_done  → tool_done(d{n}, success=True)
       dimension_failed→ tool_done(d{n}, success=False, message=error)
  3. 外层 tool_done("business_analysis", success=True)
  4. 报告 .md 作为 artifact + 助手消息持久化 + done 事件

注意:
  - cache 内部已写盘 data/qualitative/<code>_<name>/report_<date>.{json,md}
  - BA agent 不再用 cpa workspace,artifact 路径以 cache 目录为基准
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from services.agent.core import sse
from services.agent.core.qualitative import run_qualitative
from services.agent.core.qualitative.cache import QualitativeCache
from services.agent.core.qualitative.dimensions import MOCK_DIMENSION_FNS
from services.agent.core.qualitative.schema import QualitativeParams
from services.agent.core.symbol import StockRef

SseSend = Callable[[dict], Awaitable[None]]

OUTER_TOOL = "business_analysis"
OUTER_DISPLAY = "定性分析(6 维度)"


class BusinessAnalysisAgent:
    """定性分析 agent — 6 维度执行 + SSE 事件流 + 缓存复用。"""

    def __init__(
        self,
        *,
        sse_send: SseSend,
        repo,
        stock_index,
        qualitative_cache: QualitativeCache,
        dimension_fns: Optional[dict[str, Any]] = None,
        params_fallback: Optional[QualitativeParams] = None,
        current_report_date: Optional[str] = None,
        store: Any = None,
        tavily: Any = None,
        llm_factory: Optional[Callable[[str], Any]] = None,
    ):
        self.sse_send = sse_send
        self.repo = repo
        self.stock_index = stock_index
        self.cache = qualitative_cache
        # 默认用 mock 维度函数;Phase 2 注入真实实现
        self.dimension_fns = dimension_fns or MOCK_DIMENSION_FNS
        self.params_fallback = params_fallback
        self.current_report_date = current_report_date
        self.store = store
        self.tavily = tavily
        self.llm_factory = llm_factory

    async def run(self, session_id: str, ref: StockRef) -> None:
        # ----- 外层 tool_start -----
        await self.sse_send(sse.tool_start(OUTER_TOOL, OUTER_DISPLAY))
        t0 = time.time()

        # 把 output_dir 写回 session(qa_followup 路由用)
        out_dir = self.cache.data_dir / f"{ref.code}_{ref.name}"
        try:
            self.repo.upsert(session_id, stock_code=ref.code, output_dir=str(out_dir))
        except Exception:
            pass

        # ----- 维度内部事件 → SSE 映射 -----
        async def _on_event(ev: dict) -> None:
            t = ev.get("type")
            if t == "cache_hit":
                await self.sse_send(
                    sse.thinking(
                        f"命中定性分析缓存(报告期 {ev.get('report_date')}),直接复用"
                    )
                )
            elif t == "dimension_start":
                await self.sse_send(
                    sse.tool_start(
                        ev["name"].lower(),  # d1..d6 作为 tool 名
                        ev.get("title", ev["name"]),
                    )
                )
            elif t == "dimension_done":
                await self.sse_send(
                    sse.tool_done(
                        ev["name"].lower(),
                        success=True,
                        display_name=ev.get("title"),
                    )
                )
            elif t == "dimension_failed":
                await self.sse_send(
                    sse.tool_done(
                        ev["name"].lower(),
                        success=False,
                        message=ev.get("error"),
                        display_name=ev.get("title"),
                    )
                )

        # ----- 调 runner -----
        llm = self.llm_factory("business_analysis") if self.llm_factory else None
        # current_report_date:显式传入优先,否则从 DuckDB 查最新 REPORT_DATE(失败 → None)
        report_date = self.current_report_date
        if report_date is None and self.store is not None:
            try:
                report_date = self.store.query_latest_report_date(ref.code)
            except Exception:  # noqa: BLE001
                report_date = None
        try:
            report = await run_qualitative(
                ref,
                cache=self.cache,
                dimension_fns=self.dimension_fns,
                current_report_date=report_date,
                on_event=_on_event,
                store=self.store,
                tavily=self.tavily,
                llm=llm,
                params_fallback=self.params_fallback,
            )
        except Exception as e:  # noqa: BLE001
            duration = time.time() - t0
            await self.sse_send(
                sse.tool_done(
                    OUTER_TOOL, success=False, duration=duration, message=str(e)
                )
            )
            await self.sse_send(
                sse.error("BUSINESS_ANALYSIS_FAILED", str(e), phase=OUTER_TOOL)
            )
            return

        duration = time.time() - t0
        await self.sse_send(sse.tool_done(OUTER_TOOL, success=True, duration=duration))

        # ----- artifact:cache 落盘的 .md 路径 -----
        date_tag = report.report_date.replace("-", "")
        md_path: Path = out_dir / f"report_{date_tag}.md"
        try:
            text = md_path.read_text(encoding="utf-8")
        except Exception:
            # 读不到也不阻断 done(此时 artifact 仍指向路径)
            text = ""
        artifacts = [
            {
                "path": f"{out_dir.name}/{md_path.name}",
                "name": md_path.name,
            }
        ]

        # ----- 助手消息持久化 -----
        try:
            self.repo.append_message(
                session_id, role="assistant", content=text, artifacts=artifacts
            )
        except Exception:
            pass

        await self.sse_send(sse.done(text, artifacts=artifacts))
