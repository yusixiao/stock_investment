"""D2 护城河与竞争格局 — 真实实现单测。

数据源:DuckDB(长期 ROE / 毛利率)+ Tavily(护城河叙事 / 竞争对手 / 飞轮)。

LLM 输出 schema:
  {moat_type, moat_flywheel, moat_rating, competitors[{name,ticker}],
   narrative, evidence[]}

覆盖:
- 成功:store + tavily 都有数据 → LLM 拍参数
- Tavily 返 None(无 key / SDK 失败):降级为仅基于财务指标推断,不阻塞
- store 数据空 + tavily 也空 → 完全降级 ⚠️
- LLM JSON 解析失败 → ⚠️
- moat_rating 值域非法 → ⚠️
- competitors 字段缺失 → 默认空列表
- 无 LLM → ⚠️
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from services.agent.core.qualitative.dimensions.d2 import (
    DEFAULT_PARAMS,
    dimension_d2,
)
from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


def _ref() -> StockRef:
    return StockRef(code="600519.SH", name="贵州茅台", market="A")


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


def _indicator_df() -> pd.DataFrame:
    """近 5 年高 ROE + 高毛利的护城河特征。"""
    return pd.DataFrame(
        [
            {
                "REPORT_DATE": "2025-12-31",
                "ROEJQ": 32.0,
                "GROSSPROFIT_MARGIN": 91.0,
                "NETPROFIT_MARGIN": 53.0,
            },
            {
                "REPORT_DATE": "2024-12-31",
                "ROEJQ": 30.0,
                "GROSSPROFIT_MARGIN": 90.5,
                "NETPROFIT_MARGIN": 52.0,
            },
            {
                "REPORT_DATE": "2023-12-31",
                "ROEJQ": 28.0,
                "GROSSPROFIT_MARGIN": 90.0,
                "NETPROFIT_MARGIN": 51.0,
            },
            {
                "REPORT_DATE": "2022-12-31",
                "ROEJQ": 27.0,
                "GROSSPROFIT_MARGIN": 89.5,
                "NETPROFIT_MARGIN": 50.0,
            },
            {
                "REPORT_DATE": "2021-12-31",
                "ROEJQ": 26.0,
                "GROSSPROFIT_MARGIN": 89.0,
                "NETPROFIT_MARGIN": 49.0,
            },
        ]
    )


def _tavily_payload() -> dict:
    return {
        "answer": "贵州茅台凭借品牌、稀缺性与渠道形成强护城河,主要竞争对手包括五粮液、泸州老窖、洋河股份。",
        "results": [
            {
                "title": "茅台护城河分析",
                "url": "https://x",
                "content": "品牌溢价 + 稀缺产能",
            },
            {
                "title": "高端白酒竞争格局",
                "url": "https://y",
                "content": "五粮液、泸州老窖紧随",
            },
        ],
    }


_LLM_OK = """```json
{
  "moat_type": "品牌+稀缺产能+渠道",
  "moat_flywheel": true,
  "moat_rating": "强",
  "competitors": [
    {"name": "五粮液", "ticker": "000858.SZ"},
    {"name": "泸州老窖", "ticker": "000568.SZ"}
  ],
  "narrative": "茅台 ROE 长期 27%+,毛利率 90%,品牌+渠道+稀缺产能构成强护城河。",
  "evidence": ["近 5 年 ROE 均值 28.6%", "毛利率稳定 89-91%", "高端白酒第一品牌"]
}
```"""


# ===== 主路径 =====


@pytest.mark.asyncio
async def test_dimension_d2_success_full_data():
    store = _mock_store(_indicator_df())
    tavily = _mock_tavily(_tavily_payload())
    llm = _mock_llm(_LLM_OK)

    dim, partial = await dimension_d2(_ref(), store=store, tavily=tavily, llm=llm)

    assert isinstance(dim, DimensionReport)
    assert dim.name == "D2"
    assert "护城河" in dim.narrative or "品牌" in dim.narrative
    assert len(dim.evidence) == 3
    assert partial["moat_type"] == "品牌+稀缺产能+渠道"
    assert partial["moat_flywheel"] is True
    assert partial["moat_rating"] == "强"
    assert len(partial["competitors"]) == 2
    assert partial["competitors"][0] == {"name": "五粮液", "ticker": "000858.SZ"}

    # tavily 至少被调一次(护城河搜索)
    assert tavily.search_with_cache.call_count >= 1
    # LLM prompt 应包含财务关键指标 + tavily answer
    call = llm.complete.await_args
    msgs = call.args[0] if call.args else call.kwargs["messages"]
    prompt = "\n".join(m.content for m in msgs)
    assert "ROE" in prompt or "ROEJQ" in prompt
    assert "茅台" in prompt or "护城河" in prompt


# ===== 降级路径 =====


@pytest.mark.asyncio
async def test_dimension_d2_tavily_none_still_works():
    """Tavily 返 None(无 key) → 仅基于财务指标推断,不阻塞。"""
    store = _mock_store(_indicator_df())
    tavily = _mock_tavily(None)
    llm = _mock_llm(_LLM_OK)

    dim, partial = await dimension_d2(_ref(), store=store, tavily=tavily, llm=llm)

    # 应该正常拿到结果(LLM 仍被调,只是 prompt 缺 tavily 段)
    assert not dim.narrative.startswith("⚠️")
    assert partial["moat_rating"] == "强"
    assert llm.complete.await_count == 1


@pytest.mark.asyncio
async def test_dimension_d2_no_tavily_client_still_works():
    """tavily=None 注入 → 等价于无外部资讯,仅财务推断。"""
    store = _mock_store(_indicator_df())
    llm = _mock_llm(_LLM_OK)

    dim, partial = await dimension_d2(_ref(), store=store, tavily=None, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert partial["moat_rating"] == "强"


@pytest.mark.asyncio
async def test_dimension_d2_no_data_at_all():
    """store 空 + tavily None → 完全降级。"""
    store = _mock_store(pd.DataFrame())
    llm = _mock_llm(_LLM_OK)

    dim, partial = await dimension_d2(_ref(), store=store, tavily=None, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS
    assert llm.complete.await_count == 0


@pytest.mark.asyncio
async def test_dimension_d2_llm_parse_failure():
    store = _mock_store(_indicator_df())
    tavily = _mock_tavily(_tavily_payload())
    llm = _mock_llm("不是 JSON")

    dim, partial = await dimension_d2(_ref(), store=store, tavily=tavily, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d2_invalid_moat_rating():
    store = _mock_store(_indicator_df())
    llm = _mock_llm(
        """```json
{"moat_type":"x","moat_flywheel":false,"moat_rating":"超强","competitors":[],"narrative":"","evidence":[]}
```"""
    )

    dim, partial = await dimension_d2(_ref(), store=store, tavily=None, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d2_competitors_missing_defaults_empty():
    store = _mock_store(_indicator_df())
    llm = _mock_llm(
        """```json
{"moat_type":"品牌","moat_flywheel":false,"moat_rating":"中","narrative":"x","evidence":[]}
```"""
    )

    dim, partial = await dimension_d2(_ref(), store=store, tavily=None, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert partial["competitors"] == []
    assert partial["moat_rating"] == "中"


@pytest.mark.asyncio
async def test_dimension_d2_no_llm():
    store = _mock_store(_indicator_df())
    dim, partial = await dimension_d2(_ref(), store=store, tavily=None, llm=None)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d2_competitors_filters_malformed():
    """LLM 返回的 competitors 列表中混入非 dict / 缺字段的项,应过滤。"""
    store = _mock_store(_indicator_df())
    llm = _mock_llm(
        """```json
{"moat_type":"品牌","moat_flywheel":true,"moat_rating":"较强",
 "competitors":[
   {"name":"五粮液","ticker":"000858.SZ"},
   {"name":"无 ticker"},
   "字符串异常项",
   {"ticker":"无 name"},
   {"name":"洋河","ticker":"002304.SZ"}
 ],
 "narrative":"x","evidence":[]}
```"""
    )

    _, partial = await dimension_d2(_ref(), store=store, tavily=None, llm=llm)

    # 仅保留 name+ticker 都齐全的两条
    assert len(partial["competitors"]) == 2
    names = [c["name"] for c in partial["competitors"]]
    assert "五粮液" in names and "洋河" in names
