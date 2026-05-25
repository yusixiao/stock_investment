"""阶段 3 RED:business_analysis agent 入口测试。

BA agent 职责:
  - 调 run_qualitative,把内部事件映射成外层 SSE
  - cache_hit → thinking + 直接 done
  - dimension_start → tool_start(d{n}, title)
  - dimension_done → tool_done(d{n}, success=True)
  - dimension_failed → tool_done(d{n}, success=False, message=error)
  - 最终 done 事件 artifacts 指向 cache 落盘的 .md 报告
  - 助手消息持久化(否则切回历史会丢)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.agent.agents.business_analysis.agent import BusinessAnalysisAgent
from services.agent.core.qualitative.cache import QualitativeCache
from services.agent.core.qualitative.schema import (
    DimensionReport,
    QualitativeParams,
    QualitativeReport,
)
from services.agent.core.symbol import StockRef


def _ref() -> StockRef:
    return StockRef(code="600519.SH", name="贵州茅台", market="A")


def _params_full() -> QualitativeParams:
    return QualitativeParams(
        capital_intensity="capital-light",
        collection_mode="先款后货",
        moat_type="[占位]",
        moat_flywheel=False,
        moat_rating="强",
        cyclicality="非周期",
        management_rating="合格",
        mda_credibility="高",
        mda_impact="正面",
        holding_structure=False,
    )


def _make_dim(name: str) -> DimensionReport:
    return DimensionReport(
        name=name, title=f"维度{name[1:]}", narrative=f"{name} ok", evidence=[]
    )


def _mock_dim_fns(*, fail: set[str] | None = None) -> dict:
    fail = fail or set()
    fns = {}
    for i in range(1, 7):
        name = f"D{i}"

        async def _fn(ref, *, store, tavily, llm, _name=name):
            if _name in fail:
                raise RuntimeError(f"{_name} 模拟失败")
            return _make_dim(_name), {}

        fns[name] = _fn
    return fns


def _make_agent(tmp_path: Path, sent: list[dict], *, dimension_fns=None, fallback=None):
    async def sse_send(ev):
        sent.append(ev)

    repo = MagicMock()
    si = MagicMock()
    si.get_name.return_value = "贵州茅台"
    cache = QualitativeCache(tmp_path / "qual")

    agent = BusinessAnalysisAgent(
        sse_send=sse_send,
        repo=repo,
        stock_index=si,
        qualitative_cache=cache,
        dimension_fns=dimension_fns or _mock_dim_fns(),
        params_fallback=fallback or _params_full(),
        current_report_date="2024-12-31",
    )
    return agent, cache, repo


# ===== 测试 =====


class TestBaCacheMiss:
    @pytest.mark.asyncio
    async def test_runs_all_dimensions_and_emits_sse(self, tmp_path):
        sent: list[dict] = []
        agent, cache, repo = _make_agent(tmp_path, sent)
        await agent.run(session_id="s1", ref=_ref())

        types = [e["type"] for e in sent]
        # 外层 tool_start/tool_done 包裹 + 6 个维度子 tool_start/tool_done
        assert types.count("tool_start") == 7  # 1 外层 + 6 维度
        assert types.count("tool_done") == 7
        assert types[-1] == "done"

        done = sent[-1]
        # 报告 md 应作为 artifact
        assert len(done["artifacts"]) == 1
        assert done["artifacts"][0]["name"].endswith(".md")

        # 缓存已写入
        cached = cache.get("600519.SH", current_report_date="2024-12-31")
        assert cached is not None

        # 助手消息已落库
        assert repo.append_message.called


class TestBaCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_dimensions(self, tmp_path):
        sent: list[dict] = []
        agent, cache, repo = _make_agent(tmp_path, sent)
        # 预置缓存
        cache.put(
            QualitativeReport(
                stock_code="600519.SH",
                stock_name="贵州茅台",
                report_date="2024-12-31",
                dimensions=[_make_dim(f"D{i}") for i in range(1, 7)],
                params=_params_full(),
            )
        )

        await agent.run(session_id="s1", ref=_ref())

        types = [e["type"] for e in sent]
        # 命中缓存:无 6 个 dimension_start(只有 1 个外层 tool_start)
        assert types.count("tool_start") == 1
        assert types.count("tool_done") == 1
        # 应有 thinking 提示命中缓存
        assert any(e["type"] == "thinking" for e in sent)
        assert types[-1] == "done"


class TestBaDimensionFailure:
    @pytest.mark.asyncio
    async def test_failed_dimension_emits_failed_tool_done(self, tmp_path):
        sent: list[dict] = []
        agent, cache, repo = _make_agent(
            tmp_path, sent, dimension_fns=_mock_dim_fns(fail={"D3"})
        )
        await agent.run(session_id="s1", ref=_ref())

        # D3 应有失败的 tool_done(success=False)
        d3_done = [
            e for e in sent if e["type"] == "tool_done" and e.get("tool") == "d3"
        ]
        assert len(d3_done) == 1
        assert d3_done[0]["success"] is False

        # 仍应有最终 done 事件(失败容忍,不阻断流程)
        assert sent[-1]["type"] == "done"
