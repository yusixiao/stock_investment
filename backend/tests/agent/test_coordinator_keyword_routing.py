"""阶段 4 RED:Coordinator Layer 2.5 关键词路由测试。

识别到股票码后,按消息内容路由:
  - 命中关键词(定性分析/护城河/管理层/...) → business_analysis agent
  - 否则                                    → cpa(默认)

LLM 意图分类(Layer 3)未来增量补,本阶段只做规则关键词。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.agent.coordinator import Coordinator
from services.agent.core.symbol import StockRef


def _make_coord(tmp_path: Path, sent: list[dict]):
    async def sse_send(ev):
        sent.append(ev)

    repo = MagicMock()
    repo.get.return_value = {"session_id": "s1", "output_dir": None, "status": "idle"}
    si = MagicMock()
    si.get_name.return_value = "贵州茅台"

    from services.agent.core.workspace import Workspace

    ws = Workspace(tmp_path / "ws")

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=ws,
        stock_index=si,
        llm_factory=lambda p: MagicMock(),
        qualitative_dir=tmp_path / "qual",
    )
    return coord, ws


@pytest.mark.parametrize(
    "msg",
    [
        "分析 600519 的护城河",
        "看看茅台 600519 的商业模式",
        "600519 管理层怎么样",
        "600519 是周期性行业吗",
        "做一下 600519 定性分析",
        "600519 行业地位 + 治理",
        "600519 资本配置 / 战略",
    ],
)
async def test_keyword_routes_to_business_analysis(tmp_path, msg):
    """命中关键词时应路由到 business_analysis agent(发出 business_analysis tool_start)。"""
    sent: list[dict] = []
    coord, _ = _make_coord(tmp_path, sent)
    await coord.run(session_id="s1", message=msg, context=None)

    tool_starts = [e for e in sent if e["type"] == "tool_start"]
    assert tool_starts, f"应至少一个 tool_start 事件 (msg={msg!r})"
    # 第一个 tool_start 应来自 BA agent(business_analysis 外层)
    assert tool_starts[0]["tool"] == "business_analysis", (
        f"msg={msg!r} 路由错误:tool={tool_starts[0]['tool']}"
    )


async def test_no_keyword_routes_to_cpa(tmp_path):
    """无关键词时仍走 cpa。Phase 5 起 cpa 注入 qualitative_cache → 首发 phase0_qualitative。"""
    sent: list[dict] = []
    coord, _ = _make_coord(tmp_path, sent)
    await coord.run(session_id="s1", message="600519 怎么样", context=None)

    tool_starts = [e for e in sent if e["type"] == "tool_start"]
    assert tool_starts
    # Phase 5 后 cpa 第一阶段是 Phase 0(定性分析),Phase 1 紧随其后
    tools = [e["tool"] for e in tool_starts]
    assert tools[0] == "phase0_qualitative"
    assert "phase1_data_pack" in tools
