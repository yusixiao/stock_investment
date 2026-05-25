"""阶段 1.5 RED:Qualitative runner 测试。

覆盖:
- 缓存命中:不调维度函数,emit cache_hit 事件,< 1ms 返回
- 缓存未命中:顺序调 6 维度函数,emit dimension_start/done 事件
- 失败容忍:某维度抛异常 → 该维度 narrative 标 ⚠️,其他维度照跑
- force_refresh=True:即使有缓存也重跑
- 无 on_event:静默运行(cpa Phase 0 内部调用场景)
- 完成后落盘:cache.put 被调用,产物可读

骨架阶段维度函数全 mock,不依赖真实数据源。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.agent.core.qualitative.runner import run_qualitative
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
        moat_type="[非技术] 品牌",
        moat_flywheel=False,
        moat_rating="强",
        cyclicality="非周期",
        management_rating="合格",
        mda_credibility="高",
        mda_impact="正面",
        holding_structure=False,
    )


def _make_dim(
    name: str, narrative: str = "n", evidence: list[str] | None = None
) -> DimensionReport:
    return DimensionReport(
        name=name,
        title=f"维度{name[1:]}",
        narrative=narrative,
        evidence=evidence or [],
    )


def _mock_dimension_fns(*, fail: set[str] | None = None) -> dict[str, Any]:
    """构造 6 个 mock 维度函数,可指定哪些抛异常。"""
    fail = fail or set()
    fns = {}
    for i in range(1, 7):
        name = f"D{i}"

        async def _fn(ref, *, store, tavily, llm, _name=name):
            if _name in fail:
                raise RuntimeError(f"{_name} 模拟失败")
            return _make_dim(_name, narrative=f"{_name} ok"), {}

        fns[name] = _fn
    return fns


def _params_partials_full() -> dict[str, Any]:
    """6 维度返回的部分参数,合并后构成完整 QualitativeParams。"""
    return {
        "capital_intensity": "capital-light",
        "collection_mode": "先款后货",
        "moat_type": "[非技术] 品牌",
        "moat_flywheel": False,
        "moat_rating": "强",
        "cyclicality": "非周期",
        "management_rating": "合格",
        "mda_credibility": "高",
        "mda_impact": "正面",
        "holding_structure": False,
    }


# ===== 测试 =====


class TestRunnerCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_dimensions(self, tmp_path: Path):
        from services.agent.core.qualitative.cache import QualitativeCache

        cache = QualitativeCache(tmp_path)
        # 预置缓存
        cached = QualitativeReport(
            stock_code="600519.SH",
            stock_name="贵州茅台",
            report_date="2024-12-31",
            dimensions=[_make_dim(f"D{i}") for i in range(1, 7)],
            params=_params_full(),
        )
        cache.put(cached)

        events = []

        async def _on_event(e):
            events.append(e)

        # 维度函数应不被调用,这里全部抛异常以验证
        fns = _mock_dimension_fns(fail={"D1", "D2", "D3", "D4", "D5", "D6"})

        report = await run_qualitative(
            _ref(),
            cache=cache,
            dimension_fns=fns,
            current_report_date="2024-12-31",
            on_event=_on_event,
            store=MagicMock(),
            tavily=MagicMock(),
            llm=MagicMock(),
        )

        assert report.stock_code == "600519.SH"
        # 应仅 emit 一个 cache_hit 事件
        assert any(e["type"] == "cache_hit" for e in events)
        # 不应 emit dimension_start
        assert not any(e["type"] == "dimension_start" for e in events)


class TestRunnerCacheMiss:
    @pytest.mark.asyncio
    async def test_cache_miss_runs_all_dimensions(self, tmp_path: Path):
        from services.agent.core.qualitative.cache import QualitativeCache

        cache = QualitativeCache(tmp_path)
        events = []

        async def _on_event(e):
            events.append(e)

        # 自定义 mock:6 维度函数返回各自 partial params
        fns = {}
        partials = _params_partials_full()
        # 把 partials 拆成 6 维度各贡献一部分
        for i in range(1, 7):
            name = f"D{i}"

            async def _fn(ref, *, store, tavily, llm, _name=name):
                # 每个维度返回它的 dim + 部分 params(实际场景 D1 出 capital_intensity 等)
                return _make_dim(_name, narrative=f"{_name} narrative"), {}

            fns[name] = _fn

        report = await run_qualitative(
            _ref(),
            cache=cache,
            dimension_fns=fns,
            current_report_date="2024-12-31",
            on_event=_on_event,
            store=MagicMock(),
            tavily=MagicMock(),
            llm=MagicMock(),
            params_fallback=_params_full(),  # 测试场景:partial 合并不完整时兜底
        )

        # 应有 6 个 dimension_start 和 6 个 dimension_done
        assert sum(1 for e in events if e["type"] == "dimension_start") == 6
        assert sum(1 for e in events if e["type"] == "dimension_done") == 6
        # 6 维度全部成功
        assert all(d.narrative.endswith("narrative") for d in report.dimensions)
        # 缓存应已写入
        assert cache.get("600519.SH", current_report_date="2024-12-31") is not None


class TestRunnerFailureTolerance:
    @pytest.mark.asyncio
    async def test_one_dimension_fails_others_continue(self, tmp_path: Path):
        from services.agent.core.qualitative.cache import QualitativeCache

        cache = QualitativeCache(tmp_path)
        events = []

        async def _on_event(e):
            events.append(e)

        fns = _mock_dimension_fns(fail={"D3"})

        report = await run_qualitative(
            _ref(),
            cache=cache,
            dimension_fns=fns,
            current_report_date="2024-12-31",
            on_event=_on_event,
            store=MagicMock(),
            tavily=MagicMock(),
            llm=MagicMock(),
            params_fallback=_params_full(),
        )

        d3 = report.get_dimension("D3")
        assert d3 is not None
        assert d3.narrative.startswith("⚠️")
        # 其他 5 维度正常
        for i in (1, 2, 4, 5, 6):
            di = report.get_dimension(f"D{i}")
            assert di is not None
            assert di.narrative == f"D{i} ok"

        # 应 emit dimension_failed 事件
        assert any(
            e["type"] == "dimension_failed" and e["name"] == "D3" for e in events
        )


class TestRunnerForceRefresh:
    @pytest.mark.asyncio
    async def test_force_refresh_skips_cache(self, tmp_path: Path):
        from services.agent.core.qualitative.cache import QualitativeCache

        cache = QualitativeCache(tmp_path)
        # 预置缓存
        cached = QualitativeReport(
            stock_code="600519.SH",
            stock_name="贵州茅台",
            report_date="2024-12-31",
            dimensions=[_make_dim(f"D{i}", narrative="OLD") for i in range(1, 7)],
            params=_params_full(),
        )
        cache.put(cached)

        fns = _mock_dimension_fns()
        events = []

        async def _on_event(e):
            events.append(e)

        report = await run_qualitative(
            _ref(),
            cache=cache,
            dimension_fns=fns,
            current_report_date="2024-12-31",
            on_event=_on_event,
            force_refresh=True,
            store=MagicMock(),
            tavily=MagicMock(),
            llm=MagicMock(),
            params_fallback=_params_full(),
        )

        # 强制刷新 → 走维度函数,narrative 应为 "Dx ok" 而非 OLD
        assert all(d.narrative == f"{d.name} ok" for d in report.dimensions)
        assert any(e["type"] == "dimension_start" for e in events)


class TestRunnerSilent:
    @pytest.mark.asyncio
    async def test_no_on_event_runs_silently(self, tmp_path: Path):
        """on_event=None 时静默运行,这是 cpa Phase 0 内部调用的场景。"""
        from services.agent.core.qualitative.cache import QualitativeCache

        cache = QualitativeCache(tmp_path)
        fns = _mock_dimension_fns()
        report = await run_qualitative(
            _ref(),
            cache=cache,
            dimension_fns=fns,
            current_report_date="2024-12-31",
            on_event=None,
            store=MagicMock(),
            tavily=MagicMock(),
            llm=MagicMock(),
            params_fallback=_params_full(),
        )
        assert len(report.dimensions) == 6
