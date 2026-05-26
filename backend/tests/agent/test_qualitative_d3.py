"""D3 行业周期与定位 — 真实实现单测。

数据源:DuckDB(营收/净利润年度波动率,5 年)+ Tavily(行业周期叙事)。

LLM 输出 schema:
  {cyclicality, cycle_position?, industry_keywords[],
   narrative, evidence[]}

约束:
- cyclicality ∈ {强周期, 弱周期, 非周期}
- cycle_position ∈ {底部, 中段, 顶部};仅 cyclicality=强周期 时填,否则忽略 / 设 None
- industry_keywords:3-8 个

覆盖:
- 成功 — 强周期路径(给定 cycle_position)
- 成功 — 弱周期/非周期路径(cycle_position 应为 None)
- Tavily 缺失:仅基于波动率推断
- store 空 + tavily 空 → ⚠️
- LLM JSON 解析失败 → ⚠️
- cyclicality 值域非法 → ⚠️
- 强周期但缺 cycle_position → 允许(降级为 None,不阻塞)
- 非强周期但 LLM 返回 cycle_position → 强制清成 None
- industry_keywords 非 list → 默认空
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from services.agent.core.qualitative.dimensions.d3 import (
    DEFAULT_PARAMS,
    _compute_volatility,
    dimension_d3,
)
from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


def _ref() -> StockRef:
    return StockRef(code="601398.SH", name="工商银行", market="A")


def _mock_llm(payload: str) -> Any:
    llm = MagicMock()
    result = MagicMock()
    result.text = payload
    llm.complete = AsyncMock(return_value=result)
    return llm


def _mock_store(df: pd.DataFrame) -> Any:
    store = MagicMock()
    store.query = MagicMock(return_value=df)
    return store


def _mock_tavily(payload: Any) -> Any:
    tavily = MagicMock()
    tavily.search_with_cache = MagicMock(return_value=payload)
    return tavily


def _stable_df() -> pd.DataFrame:
    """非周期典型:营收/净利稳健增长。"""
    return pd.DataFrame(
        [
            {
                "REPORT_DATE": "2025-12-31",
                "TOTAL_OPERATE_INCOME": 1100,
                "PARENT_NETPROFIT": 320,
            },
            {
                "REPORT_DATE": "2024-12-31",
                "TOTAL_OPERATE_INCOME": 1050,
                "PARENT_NETPROFIT": 310,
            },
            {
                "REPORT_DATE": "2023-12-31",
                "TOTAL_OPERATE_INCOME": 1000,
                "PARENT_NETPROFIT": 300,
            },
            {
                "REPORT_DATE": "2022-12-31",
                "TOTAL_OPERATE_INCOME": 950,
                "PARENT_NETPROFIT": 290,
            },
            {
                "REPORT_DATE": "2021-12-31",
                "TOTAL_OPERATE_INCOME": 900,
                "PARENT_NETPROFIT": 280,
            },
        ]
    )


def _cyclic_df() -> pd.DataFrame:
    """强周期典型:利润大幅波动。"""
    return pd.DataFrame(
        [
            {
                "REPORT_DATE": "2025-12-31",
                "TOTAL_OPERATE_INCOME": 800,
                "PARENT_NETPROFIT": 50,
            },
            {
                "REPORT_DATE": "2024-12-31",
                "TOTAL_OPERATE_INCOME": 1500,
                "PARENT_NETPROFIT": 300,
            },
            {
                "REPORT_DATE": "2023-12-31",
                "TOTAL_OPERATE_INCOME": 1200,
                "PARENT_NETPROFIT": 200,
            },
            {
                "REPORT_DATE": "2022-12-31",
                "TOTAL_OPERATE_INCOME": 600,
                "PARENT_NETPROFIT": -50,
            },
            {
                "REPORT_DATE": "2021-12-31",
                "TOTAL_OPERATE_INCOME": 1800,
                "PARENT_NETPROFIT": 400,
            },
        ]
    )


def _tavily_payload(text: str = "行业当前处于景气底部修复阶段。") -> dict:
    return {
        "answer": text,
        "results": [{"title": "行业周期分析", "url": "https://x", "content": text}],
    }


# ===== _compute_volatility 单测 =====


def test_compute_volatility_basic():
    r = _compute_volatility(_cyclic_df())
    assert r is not None
    # 周期股波动率应显著高于平稳股
    assert r["revenue_cv"] > 0.3
    assert r["profit_cv"] > 0.5
    assert r["n_periods"] == 5


def test_compute_volatility_stable():
    r = _compute_volatility(_stable_df())
    assert r is not None
    assert r["revenue_cv"] < 0.15
    assert r["profit_cv"] < 0.10


def test_compute_volatility_empty():
    assert _compute_volatility(pd.DataFrame()) is None


# ===== dimension_d3 =====


_LLM_CYCLIC_BOTTOM = """```json
{
  "cyclicality": "强周期",
  "cycle_position": "底部",
  "industry_keywords": ["有色金属", "铜价", "全球需求", "供给侧"],
  "narrative": "近 5 年营收 CV 0.4+,净利波动剧烈,处于全球商品价格底部修复阶段。",
  "evidence": ["营收 CV 0.42", "净利 CV 1.2", "价格底部"]
}
```"""

_LLM_NON_CYCLIC = """```json
{
  "cyclicality": "非周期",
  "industry_keywords": ["银行", "存贷利差", "净息差"],
  "narrative": "稳健增长,无显著周期特征。",
  "evidence": ["营收 CV 0.1"]
}
```"""


@pytest.mark.asyncio
async def test_dimension_d3_cyclical_with_position():
    store = _mock_store(_cyclic_df())
    tavily = _mock_tavily(_tavily_payload("商品价格底部修复"))
    llm = _mock_llm(_LLM_CYCLIC_BOTTOM)

    dim, partial = await dimension_d3(_ref(), store=store, tavily=tavily, llm=llm)

    assert dim.name == "D3"
    assert not dim.narrative.startswith("⚠️")
    assert partial["cyclicality"] == "强周期"
    assert partial["cycle_position"] == "底部"
    assert "有色金属" in partial["industry_keywords"]
    assert len(partial["industry_keywords"]) == 4

    # prompt 应含波动率指标
    call = llm.complete.await_args
    msgs = call.args[0] if call.args else call.kwargs["messages"]
    prompt = "\n".join(m.content for m in msgs)
    assert "CV" in prompt or "波动" in prompt


@pytest.mark.asyncio
async def test_dimension_d3_non_cyclical_position_none():
    """cyclicality≠强周期时 cycle_position 应为 None。"""
    store = _mock_store(_stable_df())
    llm = _mock_llm(_LLM_NON_CYCLIC)

    dim, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=llm)

    assert partial["cyclicality"] == "非周期"
    assert partial["cycle_position"] is None
    assert "银行" in partial["industry_keywords"]


@pytest.mark.asyncio
async def test_dimension_d3_force_clear_position_when_not_strong_cyclical():
    """LLM 在非强周期下意外返回 cycle_position,应被清成 None。"""
    store = _mock_store(_stable_df())
    llm = _mock_llm(
        """```json
{"cyclicality":"弱周期","cycle_position":"顶部","industry_keywords":["x"],
 "narrative":"...","evidence":[]}
```"""
    )

    _, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=llm)

    assert partial["cyclicality"] == "弱周期"
    assert partial["cycle_position"] is None  # 强制清


@pytest.mark.asyncio
async def test_dimension_d3_strong_cyclical_missing_position_allowed():
    """强周期但 LLM 没给 cycle_position,允许为 None,不降级。"""
    store = _mock_store(_cyclic_df())
    llm = _mock_llm(
        """```json
{"cyclicality":"强周期","industry_keywords":["x"],"narrative":"...","evidence":[]}
```"""
    )

    dim, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert partial["cyclicality"] == "强周期"
    assert partial["cycle_position"] is None


@pytest.mark.asyncio
async def test_dimension_d3_invalid_cycle_position():
    """cyclicality=强周期 但 cycle_position 值域非法 → 清成 None,不降级整体。"""
    store = _mock_store(_cyclic_df())
    llm = _mock_llm(
        """```json
{"cyclicality":"强周期","cycle_position":"中间","industry_keywords":[],
 "narrative":"x","evidence":[]}
```"""
    )

    dim, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert partial["cyclicality"] == "强周期"
    assert partial["cycle_position"] is None


@pytest.mark.asyncio
async def test_dimension_d3_no_data_at_all():
    store = _mock_store(pd.DataFrame())
    llm = _mock_llm(_LLM_NON_CYCLIC)

    dim, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS
    assert llm.complete.await_count == 0


@pytest.mark.asyncio
async def test_dimension_d3_llm_parse_failure():
    store = _mock_store(_stable_df())
    llm = _mock_llm("not json")
    dim, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=llm)
    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d3_invalid_cyclicality():
    store = _mock_store(_stable_df())
    llm = _mock_llm(
        """```json
{"cyclicality":"中等周期","industry_keywords":[],"narrative":"x","evidence":[]}
```"""
    )
    dim, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=llm)
    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d3_keywords_not_list_defaults_empty():
    store = _mock_store(_stable_df())
    llm = _mock_llm(
        """```json
{"cyclicality":"非周期","industry_keywords":"银行业","narrative":"x","evidence":[]}
```"""
    )
    dim, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=llm)
    assert not dim.narrative.startswith("⚠️")
    assert partial["industry_keywords"] == []


@pytest.mark.asyncio
async def test_dimension_d3_no_llm():
    store = _mock_store(_stable_df())
    dim, partial = await dimension_d3(_ref(), store=store, tavily=None, llm=None)
    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS
