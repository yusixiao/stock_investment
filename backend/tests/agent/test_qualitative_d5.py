"""D5 MD&A 维度 — 真实实现单测(替换 Phase 1 mock 占位)。

覆盖:
- 成功路径:LLM 返回合法 JSON → 解析为 DimensionReport + partial params
- 无年报数据:adapter 返回空 → ⚠️ narrative + 默认 params(中性兜底)
- LLM JSON 解析失败:格式不合法 → ⚠️ narrative + 默认 params(不抛异常)
- 仅 1 期年报:跳过对比,只做单期评估,narrative 标注
- 调用契约:adapter.fetch_business_review 被以正确 code 调一次
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.agent.core.qualitative.dimensions.d5 import dimension_d5
from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


def _ref() -> StockRef:
    return StockRef(code="603939.SH", name="益丰药房", market="A")


def _annual(date: str, name: str, text: str) -> dict[str, Any]:
    """模拟 BusinessReviewRecord 的属性访问对象。"""
    obj = MagicMock()
    obj.REPORT_DATE = date
    obj.REPORT_NAME = name
    obj.BUSINESS_REVIEW = text
    return obj


def _mock_llm_json(payload: str) -> Any:
    """构造 mock LLMClient,complete() 返回固定 text。"""
    llm = MagicMock()
    result = MagicMock()
    result.text = payload
    llm.complete = AsyncMock(return_value=result)
    return llm


def _mock_adapter(records: list) -> Any:
    adapter = MagicMock()
    adapter.fetch_business_review = MagicMock(return_value=records)
    return adapter


@pytest.mark.asyncio
async def test_dimension_d5_success():
    adapter = _mock_adapter(
        [
            _annual("2025-12-31", "2025年报", "2025 年新增门店 2000 家,目标兑现 95%。"),
            _annual(
                "2024-12-31", "2024年报", "承诺 2025 年新增门店 2000 家,加速下沉。"
            ),
            _annual("2023-12-31", "2023年报", "2023 旧版"),
        ]
    )
    llm = _mock_llm_json(
        """```json
{
  "mda_credibility": "高",
  "mda_impact": "正面",
  "narrative": "管理层 2024 年报承诺 2025 新增 2000 家门店,2025 年报兑现 95%,口径一致。",
  "evidence": ["2024 年报承诺 2000 家", "2025 年报实际兑现 95%"]
}
```"""
    )

    dim, partial = await dimension_d5(_ref(), llm=llm, em_adapter=adapter)

    assert isinstance(dim, DimensionReport)
    assert dim.name == "D5"
    assert "兑现 95%" in dim.narrative
    assert len(dim.evidence) == 2
    assert partial == {"mda_credibility": "高", "mda_impact": "正面"}

    # adapter 被以正确 code 调一次
    adapter.fetch_business_review.assert_called_once_with("603939.SH")
    # LLM 被调一次,prompt 含两期年报内容
    assert llm.complete.await_count == 1
    call_args = llm.complete.await_args
    msgs = call_args.args[0] if call_args.args else call_args.kwargs["messages"]
    prompt_text = "\n".join(m.content for m in msgs)
    assert "2025年报" in prompt_text
    assert "2024年报" in prompt_text
    # 只取最近 2 期年报,2023 年报不应被塞进 prompt(避免 token 浪费)
    assert "2023 旧版" not in prompt_text


@pytest.mark.asyncio
async def test_dimension_d5_no_annual_reports_graceful():
    """没有任何年报(只有季报/中报)— 降级为 ⚠️ narrative + 默认 params。"""
    adapter = _mock_adapter(
        [
            _annual("2026-03-31", "2026一季报", "季报简短"),
            _annual("2025-09-30", "2025三季报", "三季报"),
        ]
    )
    llm = _mock_llm_json("not used")

    dim, partial = await dimension_d5(_ref(), llm=llm, em_adapter=adapter)

    assert dim.narrative.startswith("⚠️")
    assert partial == {"mda_credibility": "中", "mda_impact": "中性"}
    # 没年报就不该调 LLM,省 token
    assert llm.complete.await_count == 0


@pytest.mark.asyncio
async def test_dimension_d5_empty_data_graceful():
    """adapter 返回空列表 — 降级。"""
    adapter = _mock_adapter([])
    llm = _mock_llm_json("not used")

    dim, partial = await dimension_d5(_ref(), llm=llm, em_adapter=adapter)

    assert dim.narrative.startswith("⚠️")
    assert partial == {"mda_credibility": "中", "mda_impact": "中性"}
    assert llm.complete.await_count == 0


@pytest.mark.asyncio
async def test_dimension_d5_llm_parse_failure_graceful():
    """LLM 返回的 JSON 不合法 — narrative 标 ⚠️ + 默认 params,不抛异常。"""
    adapter = _mock_adapter(
        [
            _annual("2025-12-31", "2025年报", "..."),
            _annual("2024-12-31", "2024年报", "..."),
        ]
    )
    llm = _mock_llm_json("这不是 JSON 也没有代码块")

    dim, partial = await dimension_d5(_ref(), llm=llm, em_adapter=adapter)

    assert dim.narrative.startswith("⚠️")
    assert partial == {"mda_credibility": "中", "mda_impact": "中性"}


@pytest.mark.asyncio
async def test_dimension_d5_single_annual_report():
    """只有 1 期年报 — 跳过对比,做单期评估,narrative 标注。"""
    adapter = _mock_adapter([_annual("2025-12-31", "2025年报", "首次披露年报内容...")])
    llm = _mock_llm_json(
        """```json
{
  "mda_credibility": "中",
  "mda_impact": "中性",
  "narrative": "仅 1 期年报,无法做兑现对比,基于披露质量给中性。",
  "evidence": []
}
```"""
    )

    dim, partial = await dimension_d5(_ref(), llm=llm, em_adapter=adapter)

    assert "仅 1 期" in dim.narrative
    assert partial["mda_credibility"] == "中"
    assert llm.complete.await_count == 1


@pytest.mark.asyncio
async def test_dimension_d5_no_em_adapter_uses_default():
    """em_adapter=None 时函数自己实例化 EastMoneyAdapter — 通过 patch 验证。"""
    from unittest.mock import patch

    fake_adapter_instance = _mock_adapter([])
    fake_class = MagicMock(return_value=fake_adapter_instance)

    with patch(
        "services.agent.core.qualitative.dimensions.d5.EastMoneyAdapter",
        fake_class,
    ):
        dim, _ = await dimension_d5(_ref(), llm=_mock_llm_json("x"), em_adapter=None)

    fake_class.assert_called_once()
    fake_adapter_instance.fetch_business_review.assert_called_once()
    assert dim.narrative.startswith("⚠️")  # 空数据降级
