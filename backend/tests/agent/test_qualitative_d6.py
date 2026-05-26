"""D6 控股结构与 SOTP — 真实实现单测。

数据源:DuckDB store(query_top10_holders / query_top10_free_holders / query_holder_count) + Tavily(可选)。

LLM 输出 schema:
  {holding_structure, sotp_discount_pct, narrative, evidence[]}

覆盖:
- 控股型成功(holding_structure=True + sotp 合法)
- 单一业务成功(holding_structure=False, sotp 必须强制 None)
- 完全无数据 → ⚠️
- LLM 解析失败 / 值域非法 / sotp 越界 / sotp 缺失 / holding_structure 非 bool → ⚠️
- 无 LLM → ⚠️
- Tavily 失败不阻塞
- 持股集中度计算
- 股东类型关键词识别
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.agent.core.qualitative.dimensions.d6 import (
    DEFAULT_PARAMS,
    dimension_d6,
)
from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


def _ref() -> StockRef:
    return StockRef(code="600519.SH", name="贵州茅台", market="A")


def _ref_holding() -> StockRef:
    return StockRef(code="600030.SH", name="中信证券", market="A")


def _mock_llm(payload: str) -> Any:
    llm = MagicMock()
    result = MagicMock()
    result.text = payload
    llm.complete = AsyncMock(return_value=result)
    return llm


def _mock_store(top10=None, top10_free=None, holder_count=None) -> Any:
    store = MagicMock()
    store.query_top10_holders = MagicMock(return_value=top10 or [])
    store.query_top10_free_holders = MagicMock(return_value=top10_free or [])
    store.query_holder_count = MagicMock(return_value=holder_count or [])
    return store


def _top10_simple() -> list[dict]:
    """单一业务 — 高度集中型(茅台样)。"""
    return [
        {
            "END_DATE": "2025-09-30",
            "HOLDER_RANK": 1,
            "HOLDER_NAME": "中国贵州茅台酒厂(集团)有限责任公司",
            "HOLD_NUM_RATIO": 54.00,
            "HOLDER_TYPE": "境内法人",
            "HOLDER_STATEE": "不变",
        },
        {
            "END_DATE": "2025-09-30",
            "HOLDER_RANK": 2,
            "HOLDER_NAME": "香港中央结算有限公司",
            "HOLD_NUM_RATIO": 7.00,
            "HOLDER_TYPE": "境外法人",
        },
        {
            "END_DATE": "2025-09-30",
            "HOLDER_RANK": 3,
            "HOLDER_NAME": "贵州省国有资本运营有限责任公司",
            "HOLD_NUM_RATIO": 4.00,
            "HOLDER_TYPE": "国有",
        },
        # 旧期(应被过滤)
        {
            "END_DATE": "2025-06-30",
            "HOLDER_RANK": 1,
            "HOLDER_NAME": "ZZZ_PRIOR_PERIOD_HOLDER",
            "HOLD_NUM_RATIO": 99.0,
        },
    ]


def _top10_free_simple() -> list[dict]:
    return [
        {
            "END_DATE": "2025-09-30",
            "HOLDER_RANK": 1,
            "HOLDER_NAME": "中国贵州茅台酒厂(集团)有限责任公司",
            "FREE_HOLDNUM_RATIO": 54.00,
        },
        {
            "END_DATE": "2025-09-30",
            "HOLDER_RANK": 2,
            "HOLDER_NAME": "易方达基金 - 沪深300ETF",
            "FREE_HOLDNUM_RATIO": 1.50,
        },
    ]


def _holder_count_simple() -> list[dict]:
    return [
        {
            "END_DATE": "2025-09-30",
            "HOLDER_NUM": 198000,
            "PRE_END_DATE": "2025-06-30",
            "PRE_HOLDER_NUM": 200000,
            "HOLDER_NUM_RATIO": -1.0,
        }
    ]


_LLM_NOT_HOLDING = """```json
{
  "holding_structure": false,
  "sotp_discount_pct": null,
  "narrative": "贵州茅台主营单一为白酒,控股股东茅台集团持股 54%,无显著多元化业务,不构成 SOTP 折价场景。",
  "evidence": [
    "top1 茅台集团 54.00% 绝对控股",
    "无独立子公司业务披露",
    "Tavily 检索未提及多元化板块"
  ]
}
```"""


_LLM_HOLDING = """```json
{
  "holding_structure": true,
  "sotp_discount_pct": 0.25,
  "narrative": "中信证券实为多元金融控股平台,涵盖经纪、投行、资管、自营等业务线,业务跨度大,综合金融折价取 25%。",
  "evidence": [
    "中信集团控股 16% 综合金融背景",
    "业务板块超过 4 个相互独立",
    "Tavily 提及 SOTP 估值"
  ]
}
```"""


# ===== 单一业务路径 =====


@pytest.mark.asyncio
async def test_dimension_d6_single_business_success():
    store = _mock_store(_top10_simple(), _top10_free_simple(), _holder_count_simple())
    llm = _mock_llm(_LLM_NOT_HOLDING)

    dim, partial = await dimension_d6(_ref(), store=store, llm=llm)

    assert isinstance(dim, DimensionReport)
    assert dim.name == "D6"
    assert not dim.narrative.startswith("⚠️")
    assert partial == {"holding_structure": False, "sotp_discount_pct": None}
    assert len(dim.evidence) == 3
    assert llm.complete.await_count == 1

    # Prompt 应包含集中度统计
    call = llm.complete.await_args
    msgs = call.args[0] if call.args else call.kwargs["messages"]
    prompt = "\n".join(m.content for m in msgs)
    assert "持股集中度" in prompt
    assert "top1 54.0%" in prompt or "top1 54.00%" in prompt
    # 茅台集团 在十大股东
    assert "茅台" in prompt
    # 旧期 (2025-06-30) 不应出现
    assert "ZZZ_PRIOR_PERIOD_HOLDER" not in prompt
    # 股东类型分类:茅台集团→集团/控股,香港中央→境外,贵州省国资→国资
    assert "国资" in prompt
    assert "集团/控股" in prompt
    assert "境外" in prompt


@pytest.mark.asyncio
async def test_dimension_d6_holding_structure_with_discount():
    """holding_structure=True 时 sotp 必须保留。"""
    store = _mock_store(_top10_simple(), _top10_free_simple(), _holder_count_simple())
    llm = _mock_llm(_LLM_HOLDING)

    dim, partial = await dimension_d6(_ref_holding(), store=store, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert partial == {"holding_structure": True, "sotp_discount_pct": 0.25}


@pytest.mark.asyncio
async def test_dimension_d6_force_sotp_none_when_not_holding():
    """LLM 错误地在 holding_structure=False 时也填了 sotp,实现应强制覆盖为 None。"""
    store = _mock_store(_top10_simple())
    llm = _mock_llm(
        """```json
{"holding_structure": false, "sotp_discount_pct": 0.30, "narrative": "x", "evidence": []}
```"""
    )

    _, partial = await dimension_d6(_ref(), store=store, llm=llm)

    assert partial == {"holding_structure": False, "sotp_discount_pct": None}


# ===== 降级路径 =====


@pytest.mark.asyncio
async def test_dimension_d6_no_data_at_all():
    store = _mock_store([], [], [])
    llm = _mock_llm(_LLM_NOT_HOLDING)

    dim, partial = await dimension_d6(_ref(), store=store, tavily=None, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS
    assert llm.complete.await_count == 0


@pytest.mark.asyncio
async def test_dimension_d6_no_llm():
    store = _mock_store(_top10_simple())
    dim, partial = await dimension_d6(_ref(), store=store, llm=None)
    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d6_llm_parse_failure():
    store = _mock_store(_top10_simple())
    llm = _mock_llm("not json")

    dim, partial = await dimension_d6(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d6_holding_structure_not_bool():
    store = _mock_store(_top10_simple())
    llm = _mock_llm(
        """```json
{"holding_structure":"yes","sotp_discount_pct":0.2,"narrative":"x","evidence":[]}
```"""
    )

    dim, partial = await dimension_d6(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d6_sotp_missing_when_holding():
    store = _mock_store(_top10_simple())
    llm = _mock_llm(
        """```json
{"holding_structure":true,"sotp_discount_pct":null,"narrative":"x","evidence":[]}
```"""
    )

    dim, partial = await dimension_d6(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d6_sotp_out_of_range():
    store = _mock_store(_top10_simple())
    llm = _mock_llm(
        """```json
{"holding_structure":true,"sotp_discount_pct":1.5,"narrative":"x","evidence":[]}
```"""
    )

    dim, partial = await dimension_d6(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d6_sotp_non_numeric():
    store = _mock_store(_top10_simple())
    llm = _mock_llm(
        """```json
{"holding_structure":true,"sotp_discount_pct":"high","narrative":"x","evidence":[]}
```"""
    )

    dim, partial = await dimension_d6(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d6_llm_exception_degrades():
    store = _mock_store(_top10_simple())
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=TimeoutError("llm timeout"))

    dim, partial = await dimension_d6(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert "LLM 调用失败" in dim.narrative
    assert partial == DEFAULT_PARAMS


# ===== Tavily =====


@pytest.mark.asyncio
async def test_dimension_d6_tavily_in_prompt():
    store = _mock_store(_top10_simple())
    llm = _mock_llm(_LLM_NOT_HOLDING)
    tavily = MagicMock()
    tavily.search_with_cache = MagicMock(
        return_value={
            "answer": "茅台主营单一白酒,无多元化业务",
            "results": [{"title": "年报", "url": "u", "content": "白酒"}],
        }
    )

    await dimension_d6(_ref(), store=store, tavily=tavily, llm=llm)

    tavily.search_with_cache.assert_called_once()
    kwargs = tavily.search_with_cache.call_args.kwargs
    assert kwargs["section"] == "d6_holding_structure"
    assert kwargs["code"] == "600519.SH"
    assert "贵州茅台" in kwargs["query"]

    call = llm.complete.await_args
    prompt = "\n".join(m.content for m in (call.args[0] if call.args else []))
    assert "无多元化业务" in prompt


@pytest.mark.asyncio
async def test_dimension_d6_tavily_failure_does_not_block():
    store = _mock_store(_top10_simple())
    llm = _mock_llm(_LLM_NOT_HOLDING)
    tavily = MagicMock()
    tavily.search_with_cache = MagicMock(side_effect=RuntimeError("tavily 503"))

    dim, _ = await dimension_d6(_ref(), store=store, tavily=tavily, llm=llm)

    assert not dim.narrative.startswith("⚠️")


@pytest.mark.asyncio
async def test_dimension_d6_only_tavily_no_holders_still_runs_llm():
    store = _mock_store([], [], [])
    llm = _mock_llm(_LLM_NOT_HOLDING)
    tavily = MagicMock()
    tavily.search_with_cache = MagicMock(
        return_value={
            "answer": "x",
            "results": [{"title": "t", "url": "u", "content": "c"}],
        }
    )

    dim, _ = await dimension_d6(_ref(), store=store, tavily=tavily, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert llm.complete.await_count == 1


# ===== mock alias =====


def test_mock_dimension_d6_is_real_implementation():
    from services.agent.core.qualitative.dimensions.d6 import (
        dimension_d6 as real,
        mock_dimension_d6 as mock,
    )

    assert mock is real
