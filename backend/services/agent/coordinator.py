"""问股 Coordinator — 多 agent 路由器(4 层 fallback 设计)。

路由顺序:
  Layer 1 (规则): session.output_dir 已有完整报告 → qa_followup
  Layer 2 (规则): 无股票上下文 + 消息无股票码 → clarify(硬编码澄清,不调 LLM)
  Layer 3 (LLM): 识别到股票码 → 意图分类器 → AGENT_REGISTRY[name].run()
                 (TODO 阶段 2:目前未实现,直接走 Layer 4 兜底)
  Layer 4 (兜底): 默认 agent = "cpa"

任何异常都通过 sse.error 事件输出,不向上抛。
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable, Optional

from services.agent.agents import AGENT_REGISTRY
from services.agent.core import sse
from services.agent.core.qualitative.cache import QualitativeCache
from services.agent.core.symbol import extract
from services.system_config.llm_client import LLMClient, LLMError, Message  # noqa: F401

SseSend = Callable[[dict], Awaitable[None]]

# Layer 4 兜底 agent(意图分类失败/未实现时)
DEFAULT_AGENT = "cpa"

# Layer 2.5 关键词路由 → business_analysis agent
# 命中任一关键词即路由(简单子串匹配,大小写不敏感对中文无影响)
BUSINESS_ANALYSIS_KEYWORDS = (
    "定性分析",
    "商业模式",
    "护城河",
    "管理层",
    "周期性",
    "行业地位",
    "治理",
    "资本配置",
    "战略",
)


class Coordinator:
    """Coordinator 负责按 4 层 fallback 路由到合适 agent 并发出 SSE 事件流。"""

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
        qualitative_dir: Optional[Path] = None,
    ):
        self.sse_send = sse_send
        self.repo = repo
        self.workspace = workspace
        self.stock_index = stock_index
        self.llm_factory = llm_factory
        # 透传给 agent 的真实数据依赖(单测可不传)
        self.store = store
        self.indicators = indicators
        # 可选 Tavily web search(§8 行业 / §10 ESG);无 key 自动降级
        self.tavily = tavily
        # 定性分析缓存目录(BA agent / cpa Phase 0 共享)
        # 优先级:显式参数 > DSA_QUALITATIVE_DIR 环境变量 > config.QUALITATIVE_DIR
        if qualitative_dir is None:
            import os

            env_dir = os.getenv("DSA_QUALITATIVE_DIR")
            if env_dir:
                qualitative_dir = Path(env_dir)
            else:
                from config import QUALITATIVE_DIR

                qualitative_dir = QUALITATIVE_DIR
        self._qualitative_cache = QualitativeCache(qualitative_dir)

    async def run(
        self,
        *,
        session_id: str,
        message: str,
        context: Optional[dict],
    ) -> None:
        try:
            # ---- Layer 1: 已有完整报告 → qa_followup ----
            session = self.repo.get(session_id) or {}
            output_dir = session.get("output_dir")
            if output_dir and self._has_completed_report(Path(output_dir)):
                return await self._run_qa_followup(
                    session_id, message, Path(output_dir)
                )

            # ---- Layer 2: 无股票上下文 → 硬编码澄清(不调 LLM)----
            ref = extract(message, context, stock_index=self.stock_index)
            if ref is None:
                return await self._run_clarify(session_id)

            # ---- Layer 2.5: 关键词路由(规则,毫秒级)----
            agent_name = self._route_by_keywords(message)

            # ---- Layer 3: LLM 意图分类(TODO 后续阶段)----
            # if agent_name is None:
            #     agent_name = await self._classify_intent(message, ref)

            # ---- Layer 4: 兜底默认 agent ----
            if agent_name is None:
                agent_name = DEFAULT_AGENT

            agent = self._build_agent(agent_name)
            return await agent.run(session_id, ref)
        except LLMError as e:
            await self.sse_send(sse.error(e.code, e.message))
        except Exception as e:  # noqa: BLE001 — 兜底防漏
            await self.sse_send(sse.error("INTERNAL", str(e)))

    # ===== 内部 =====

    def _route_by_keywords(self, message: str) -> Optional[str]:
        """Layer 2.5 关键词路由。命中 → 返回 agent name;未命中 → None。"""
        for kw in BUSINESS_ANALYSIS_KEYWORDS:
            if kw in message:
                return "business_analysis"
        return None

    def _build_agent(self, agent_name: str):
        """按 agent_name 实例化 agent,屏蔽不同构造器签名差异。"""
        agent_cls = AGENT_REGISTRY[agent_name]
        if agent_name == "business_analysis":
            return agent_cls(
                sse_send=self.sse_send,
                repo=self.repo,
                stock_index=self.stock_index,
                qualitative_cache=self._qualitative_cache,
                store=self.store,
                tavily=self.tavily,
                llm_factory=self.llm_factory,
            )
        # cpa 与未来同构 agent 走标准签名
        kwargs = dict(
            sse_send=self.sse_send,
            repo=self.repo,
            workspace=self.workspace,
            stock_index=self.stock_index,
            llm_factory=self.llm_factory,
            store=self.store,
            indicators=self.indicators,
            tavily=self.tavily,
        )
        # cpa 接受 Phase 0 定性分析依赖(其他同构 agent 若不接受会被忽略)
        if agent_name == "cpa":
            kwargs["qualitative_cache"] = self._qualitative_cache
        return agent_cls(**kwargs)

    def _has_completed_report(self, d: Path) -> bool:
        try:
            meta = self.workspace.read_meta(d)
        except Exception:
            return False
        return (
            meta.get("phases", {}).get("phase3_valuation", {}).get("status") == "done"
        )

    # 硬编码澄清文案 — 未识别到股票码时引导用户提供明确意图。
    # 不调 LLM,即使配置缺失/网络挂掉也能稳定响应。
    _CLARIFY_TEXT = (
        "我是问股助手,需要你告诉我想分析哪只股票才能开始。\n\n"
        "请在消息里包含股票名称或代码,例如:\n"
        "- A 股:`分析比亚迪 002594.SZ` / `看看 600519`\n"
        "- 港股:`腾讯 00700.HK`\n"
        "- 美股:`AAPL 怎么样`\n\n"
        "已有分析报告时,你也可以直接追问报告中的细节。"
    )

    async def _run_clarify(self, session_id: str) -> None:
        text = self._CLARIFY_TEXT
        self.repo.append_message(
            session_id,
            role="assistant",
            content=text,
            tokens_in=0,
            tokens_out=0,
        )
        await self.sse_send(sse.done(text, artifacts=[]))

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
