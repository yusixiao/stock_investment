"""D1 商业模式与资本特征 — 真实实现单测(替换 Phase 1 mock 占位)。

数据源:DuckDB(纯本地,无外网)。
- balance: TOTAL_ASSETS / FIXED_ASSETS / GOODWILL / INTANGIBLE_ASSETS / ACCOUNTS_RECE / ADVANCE_RECEIVABLES
- cashflow: NETCASH_OPERATE / CONSTRUCT_LONG_ASSET (capex 代理)
- income:   TOTAL_OPERATE_INCOME

逻辑:计算近 3 年均值比率 → LLM 拍 capital_intensity + collection_mode。

覆盖:
- 成功:LLM 返回 JSON 含两参数 → 解析为 partial
- 数据为空:store 返回空 DataFrame → ⚠️ 降级 + 默认中性
- LLM JSON 解析失败 → ⚠️ 降级
- 值域非法(LLM 输出非 Literal 值)→ ⚠️ 降级
- 无 LLM 注入 → ⚠️ 降级
- 比率计算正确性(asset_intensity / capex_ratio / ar_ratio / ad_ratio / ocf_ratio)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from services.agent.core.qualitative.dimensions.d1 import (
    DEFAULT_PARAMS,
    _compute_ratios,
    dimension_d1,
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


def _sample_df() -> pd.DataFrame:
    """3 年模拟数据:茅台式资本轻 + 订阅预收特征(ADVANCE>>ACCOUNTS,OCF 健康)。"""
    return pd.DataFrame(
        [
            {
                "REPORT_DATE": "2025-12-31",
                "TOTAL_ASSETS": 3_000_000,
                "FIXED_ASSETS": 200_000,
                "GOODWILL": 0,
                "INTANGIBLE_ASSETS": 50_000,
                "ACCOUNTS_RECE": 5_000,
                "ADVANCE_RECEIVABLES": 250_000,
                "NETCASH_OPERATE": 800_000,
                "CONSTRUCT_LONG_ASSET": 50_000,
                "TOTAL_OPERATE_INCOME": 1_500_000,
            },
            {
                "REPORT_DATE": "2024-12-31",
                "TOTAL_ASSETS": 2_700_000,
                "FIXED_ASSETS": 180_000,
                "GOODWILL": 0,
                "INTANGIBLE_ASSETS": 45_000,
                "ACCOUNTS_RECE": 4_500,
                "ADVANCE_RECEIVABLES": 220_000,
                "NETCASH_OPERATE": 700_000,
                "CONSTRUCT_LONG_ASSET": 40_000,
                "TOTAL_OPERATE_INCOME": 1_300_000,
            },
            {
                "REPORT_DATE": "2023-12-31",
                "TOTAL_ASSETS": 2_400_000,
                "FIXED_ASSETS": 160_000,
                "GOODWILL": 0,
                "INTANGIBLE_ASSETS": 40_000,
                "ACCOUNTS_RECE": 4_000,
                "ADVANCE_RECEIVABLES": 200_000,
                "NETCASH_OPERATE": 600_000,
                "CONSTRUCT_LONG_ASSET": 30_000,
                "TOTAL_OPERATE_INCOME": 1_100_000,
            },
        ]
    )


# ===== _compute_ratios 单元测试 =====


def test_compute_ratios_basic():
    df = _sample_df()
    r = _compute_ratios(df)
    # asset_intensity = avg((FA+GW+IA)/TA)
    # 2025: (200+0+50)/3000 = 0.0833;2024: (180+0+45)/2700 = 0.0833;2023: 同 ≈0.0833
    assert r["asset_intensity"] == pytest.approx(0.0833, abs=0.005)
    # capex_ratio = avg(CONSTRUCT/REVENUE):2025 50/1500=0.0333,均值 ~0.031
    assert r["capex_ratio"] == pytest.approx(0.0306, abs=0.005)
    # ar_ratio 应收/营收:2025 5000/1500000 ≈ 0.0033,极小
    assert r["ar_ratio"] < 0.01
    # ad_ratio 预收/营收:2025 250000/1500000 ≈ 0.167,显著
    assert r["ad_ratio"] > 0.15
    # ocf_ratio 经营现金流/营收:2025 800000/1500000 ≈ 0.533
    assert r["ocf_ratio"] > 0.4


def test_compute_ratios_empty_df():
    r = _compute_ratios(pd.DataFrame())
    assert r is None


def test_compute_ratios_skips_zero_revenue():
    """REVENUE=0 行应被跳过,不应除零崩溃。"""
    df = pd.DataFrame(
        [
            {
                "REPORT_DATE": "2025-12-31",
                "TOTAL_ASSETS": 1000,
                "FIXED_ASSETS": 100,
                "GOODWILL": 0,
                "INTANGIBLE_ASSETS": 0,
                "ACCOUNTS_RECE": 10,
                "ADVANCE_RECEIVABLES": 5,
                "NETCASH_OPERATE": 100,
                "CONSTRUCT_LONG_ASSET": 10,
                "TOTAL_OPERATE_INCOME": 0,  # 应被跳
            },
            {
                "REPORT_DATE": "2024-12-31",
                "TOTAL_ASSETS": 1000,
                "FIXED_ASSETS": 100,
                "GOODWILL": 0,
                "INTANGIBLE_ASSETS": 0,
                "ACCOUNTS_RECE": 10,
                "ADVANCE_RECEIVABLES": 5,
                "NETCASH_OPERATE": 100,
                "CONSTRUCT_LONG_ASSET": 10,
                "TOTAL_OPERATE_INCOME": 500,
            },
        ]
    )
    r = _compute_ratios(df)
    assert r is not None
    assert r["capex_ratio"] == pytest.approx(0.02)


# ===== dimension_d1 集成测试 =====


@pytest.mark.asyncio
async def test_dimension_d1_success():
    store = _mock_store(_sample_df())
    llm = _mock_llm(
        """```json
{
  "capital_intensity": "capital-light",
  "collection_mode": "订阅预收",
  "narrative": "茅台资本轻、预收主导,经营现金流健康。",
  "evidence": ["固定资产占比 ~8%", "预收账款/营收 16.7%", "经营性现金流/营收 53%"]
}
```"""
    )

    dim, partial = await dimension_d1(_ref(), store=store, llm=llm)

    assert isinstance(dim, DimensionReport)
    assert dim.name == "D1"
    assert "茅台" in dim.narrative or "预收" in dim.narrative
    assert len(dim.evidence) == 3
    assert partial == {
        "capital_intensity": "capital-light",
        "collection_mode": "订阅预收",
    }
    # store.query 至少被调一次
    assert store.query.call_count >= 1


@pytest.mark.asyncio
async def test_dimension_d1_empty_data_graceful():
    store = _mock_store(pd.DataFrame())
    llm = _mock_llm("not used")

    dim, partial = await dimension_d1(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS
    assert llm.complete.await_count == 0  # 数据空就不该调 LLM


@pytest.mark.asyncio
async def test_dimension_d1_llm_parse_failure_graceful():
    store = _mock_store(_sample_df())
    llm = _mock_llm("不是 JSON")

    dim, partial = await dimension_d1(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d1_invalid_value_domain_graceful():
    """LLM 输出值域非法(超出 Literal)→ 降级。"""
    store = _mock_store(_sample_df())
    llm = _mock_llm(
        """```json
{
  "capital_intensity": "中等",
  "collection_mode": "现金交易",
  "narrative": "...",
  "evidence": []
}
```"""
    )

    dim, partial = await dimension_d1(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d1_no_llm_graceful():
    store = _mock_store(_sample_df())
    dim, partial = await dimension_d1(_ref(), store=store, llm=None)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d1_store_query_exception_graceful():
    store = MagicMock()
    store.query = MagicMock(side_effect=RuntimeError("DuckDB boom"))
    llm = _mock_llm("not used")

    dim, partial = await dimension_d1(_ref(), store=store, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS
    assert llm.complete.await_count == 0


@pytest.mark.asyncio
async def test_dimension_d1_no_store_graceful():
    """store=None 时不应崩溃,直接降级。"""
    llm = _mock_llm("x")
    dim, partial = await dimension_d1(_ref(), store=None, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d1_prompt_includes_ratios():
    """prompt 应包含计算出的关键比率,LLM 才有依据决策。"""
    store = _mock_store(_sample_df())
    llm = _mock_llm(
        """```json
{"capital_intensity":"capital-light","collection_mode":"订阅预收","narrative":"x","evidence":[]}
```"""
    )

    await dimension_d1(_ref(), store=store, llm=llm)

    call = llm.complete.await_args
    msgs = call.args[0] if call.args else call.kwargs["messages"]
    prompt_text = "\n".join(m.content for m in msgs)
    # 关键比率应以可读形式出现
    assert "asset_intensity" in prompt_text or "资产强度" in prompt_text
    assert "ad_ratio" in prompt_text or "预收" in prompt_text
