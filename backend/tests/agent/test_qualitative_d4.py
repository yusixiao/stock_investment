"""D4 管理层与治理 — 真实实现单测。

数据源:
- A 股:EastMoneyAdapter.fetch_company_management → emweb F10
- HK / US:YFinanceAdapter.fetch_company_management → companyOfficers + insider_transactions
- Tavily(可选):治理事件搜索

LLM 输出 schema:
  {management_rating, narrative, evidence[]}

覆盖:
- A 股成功路径(em_adapter 注入)
- HK / US 成功路径(yf_adapter 注入,无 tenure 数据)
- adapter 抛异常 → ⚠️
- 完全无数据 → ⚠️
- LLM JSON 解析失败 → ⚠️
- 值域非法("良好") → ⚠️
- 无 LLM → ⚠️
- 核心高管识别:仅含 董事长/总经理/CFO/董秘 等关键词的入选
- 近 12 月窗口过滤:超过 365 天的变动不计入 prompt
- 净额计算:增减持符号汇总
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.management import ExecutiveHoldChangeRecord, ExecutiveRecord
from services.agent.core.qualitative.dimensions.d4 import (
    DEFAULT_PARAMS,
    dimension_d4,
)
from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef


# ===== fixtures =====


def _ref_a() -> StockRef:
    return StockRef(code="600519.SH", name="贵州茅台", market="A")


def _ref_hk() -> StockRef:
    return StockRef(code="00700.HK", name="腾讯控股", market="HK")


def _ref_us() -> StockRef:
    return StockRef(code="AAPL", name="Apple Inc.", market="US")


def _mock_llm(payload: str) -> Any:
    llm = MagicMock()
    result = MagicMock()
    result.text = payload
    llm.complete = AsyncMock(return_value=result)
    return llm


def _mock_adapter(executives: list, hold_changes: list) -> Any:
    adapter = MagicMock()
    adapter.fetch_company_management = MagicMock(
        return_value=(executives, hold_changes)
    )
    return adapter


def _exec_a(name: str, position: str, *, age: int = 50, tenure_year: int = 2020):
    return ExecutiveRecord(
        name=name,
        position=position,
        age=age,
        education="本科",
        tenure_text=f"{tenure_year}-05-01至今",
        source="eastmoney",
    )


def _change_a(name: str, change_num: float, days_ago: int, *, position: str = "董事长"):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    return ExecutiveHoldChangeRecord(
        end_date=d,
        executive_name=name,
        position=position,
        change_num=change_num,
        average_price=720.0,
        trade_way="二级市场买卖",
        source="eastmoney",
    )


def _executives_a() -> list:
    return [
        _exec_a("陈华", "董事长", age=54, tenure_year=2025),
        _exec_a("王莉", "总经理", age=50, tenure_year=2022),
        _exec_a("万波", "财务总监,董事会秘书", age=46, tenure_year=2020),
        _exec_a("李四", "独立董事", age=60, tenure_year=2019),  # 非核心
        _exec_a("赵六", "监事", age=55, tenure_year=2018),  # 非核心
    ]


def _hold_changes_a() -> list:
    return [
        _change_a("万波", -700, 45, position="财务总监"),  # 近 12 月减持
        _change_a("王莉", 1000, 90, position="总经理"),  # 近 12 月增持
        _change_a("陈华", -50000, 800, position="董事长"),  # 超 12 月,过滤
    ]


_LLM_OK = """```json
{
  "management_rating": "合格",
  "narrative": "茅台核心高管(董事长陈华、总经理王莉)任期稳定,财务总监万波小幅减持 700 股属正常调仓,无监管处罚,资本配置中性。综合给予合格评级,价值陷阱排查不触发。",
  "evidence": [
    "核心高管 3 人,平均任期 4 年",
    "近 12 月净增持 300 股(增持 1 笔 / 减持 1 笔)",
    "无重大监管事件"
  ]
}
```"""


# ===== A 股主路径 =====


@pytest.mark.asyncio
async def test_dimension_d4_a_share_success():
    em = _mock_adapter(_executives_a(), _hold_changes_a())
    llm = _mock_llm(_LLM_OK)

    dim, partial = await dimension_d4(_ref_a(), em_adapter=em, llm=llm)

    assert isinstance(dim, DimensionReport)
    assert dim.name == "D4"
    assert not dim.narrative.startswith("⚠️")
    assert partial == {"management_rating": "合格"}
    assert len(dim.evidence) == 3
    assert llm.complete.await_count == 1
    em.fetch_company_management.assert_called_once_with("600519.SH")

    # Prompt 应包含核心高管(陈华/王莉/万波),且不包含独立董事 / 监事
    call = llm.complete.await_args
    msgs = call.args[0] if call.args else call.kwargs["messages"]
    prompt = "\n".join(m.content for m in msgs)
    assert "陈华" in prompt and "王莉" in prompt and "万波" in prompt
    # 非核心高管(独立董事 李四 / 监事 赵六)不应出现在核心高管段落
    assert "李四" not in prompt
    assert "赵六" not in prompt
    # 任期段
    assert "平均任期" in prompt
    # 持股变动:近 12 月只有 2 笔,800 天前的 -50000 不应进 prompt
    assert "万波" in prompt
    assert "-50,000" not in prompt and "-50000" not in prompt


@pytest.mark.asyncio
async def test_dimension_d4_a_share_change_window_filters_old():
    """超过 12 月的变动不进 prompt 也不进净额。"""
    execs = [_exec_a("陈华", "董事长")]
    changes = [
        _change_a("陈华", 100, 30),  # 1 月前 增 100
        _change_a("陈华", -200, 60),  # 2 月前 减 200
        _change_a("陈华", 999999, 800),  # 800 天前(过滤)
    ]
    em = _mock_adapter(execs, changes)
    llm = _mock_llm(_LLM_OK)

    await dimension_d4(_ref_a(), em_adapter=em, llm=llm)

    call = llm.complete.await_args
    prompt = "\n".join(m.content for m in (call.args[0] if call.args else []))
    # 净额 = +100 + (-200) = -100;不应出现 999999
    assert "999,999" not in prompt and "999999" not in prompt
    assert "-100" in prompt or "−100" in prompt


# ===== HK / US 路径 =====


@pytest.mark.asyncio
async def test_dimension_d4_hk_success_no_tenure():
    """HK 走 yf_adapter,无 tenure 数据 → prompt 写「跳过该项」。"""
    execs = [
        ExecutiveRecord(
            name="Pony Ma",
            position="Chairman & CEO",
            age=53,
            source="yfinance",
        ),
        ExecutiveRecord(
            name="Martin Lau",
            position="President",
            age=51,
            source="yfinance",
        ),
    ]
    yf = _mock_adapter(execs, [])
    llm = _mock_llm(_LLM_OK)

    dim, partial = await dimension_d4(_ref_hk(), yf_adapter=yf, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert partial["management_rating"] == "合格"
    yf.fetch_company_management.assert_called_once_with("00700.HK")

    call = llm.complete.await_args
    prompt = "\n".join(m.content for m in (call.args[0] if call.args else []))
    assert "Pony Ma" in prompt
    # tenure_text 缺失 → 走 "跳过该项指标"
    assert "跳过该项指标" in prompt
    # 持股变动空 → 写 "(近 12 月无持股变动记录)"
    assert "无持股变动记录" in prompt


@pytest.mark.asyncio
async def test_dimension_d4_us_success():
    execs = [
        ExecutiveRecord(
            name="Tim Cook", position="Chief Executive Officer", source="yfinance"
        )
    ]
    changes = [
        ExecutiveHoldChangeRecord(
            end_date=(date.today() - timedelta(days=30)).isoformat(),
            executive_name="Tim Cook",
            position="CEO",
            change_num=-50000,
            average_price=180.0,
            trade_way="Open Market Sell",
            source="yfinance",
        )
    ]
    yf = _mock_adapter(execs, changes)
    llm = _mock_llm(_LLM_OK)

    dim, _ = await dimension_d4(_ref_us(), yf_adapter=yf, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    yf.fetch_company_management.assert_called_once_with("AAPL")


# ===== 降级路径 =====


@pytest.mark.asyncio
async def test_dimension_d4_adapter_raises():
    em = MagicMock()
    em.fetch_company_management = MagicMock(side_effect=RuntimeError("HTTP 503"))
    llm = _mock_llm(_LLM_OK)

    dim, partial = await dimension_d4(_ref_a(), em_adapter=em, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert "高管数据获取失败" in dim.narrative
    assert partial == DEFAULT_PARAMS
    assert llm.complete.await_count == 0


@pytest.mark.asyncio
async def test_dimension_d4_no_data_at_all():
    """executives + 持股变动 + tavily 全空 → ⚠️ 默认观察期。"""
    em = _mock_adapter([], [])
    llm = _mock_llm(_LLM_OK)

    dim, partial = await dimension_d4(_ref_a(), em_adapter=em, tavily=None, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS
    assert llm.complete.await_count == 0


@pytest.mark.asyncio
async def test_dimension_d4_no_llm():
    em = _mock_adapter(_executives_a(), _hold_changes_a())

    dim, partial = await dimension_d4(_ref_a(), em_adapter=em, llm=None)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d4_llm_parse_failure():
    em = _mock_adapter(_executives_a(), _hold_changes_a())
    llm = _mock_llm("not json at all")

    dim, partial = await dimension_d4(_ref_a(), em_adapter=em, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d4_invalid_rating():
    em = _mock_adapter(_executives_a(), _hold_changes_a())
    llm = _mock_llm(
        """```json
{"management_rating":"良好","narrative":"x","evidence":[]}
```"""
    )

    dim, partial = await dimension_d4(_ref_a(), em_adapter=em, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert partial == DEFAULT_PARAMS


@pytest.mark.asyncio
async def test_dimension_d4_llm_exception_degrades():
    em = _mock_adapter(_executives_a(), _hold_changes_a())
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=TimeoutError("llm timeout"))

    dim, partial = await dimension_d4(_ref_a(), em_adapter=em, llm=llm)

    assert dim.narrative.startswith("⚠️")
    assert "LLM 调用失败" in dim.narrative
    assert partial == DEFAULT_PARAMS


# ===== Tavily 集成 =====


@pytest.mark.asyncio
async def test_dimension_d4_tavily_payload_in_prompt():
    em = _mock_adapter(_executives_a(), _hold_changes_a())
    llm = _mock_llm(_LLM_OK)
    tavily = MagicMock()
    tavily.search_with_cache = MagicMock(
        return_value={
            "answer": "茅台近期无重大治理事件",
            "results": [
                {"title": "茅台 2025 年报", "url": "https://x", "content": "无处罚"},
            ],
        }
    )

    await dimension_d4(_ref_a(), em_adapter=em, tavily=tavily, llm=llm)

    tavily.search_with_cache.assert_called_once()
    kwargs = tavily.search_with_cache.call_args.kwargs
    assert kwargs["section"] == "d4_management"
    assert kwargs["code"] == "600519.SH"
    assert "贵州茅台" in kwargs["query"]

    call = llm.complete.await_args
    prompt = "\n".join(m.content for m in (call.args[0] if call.args else []))
    assert "无重大治理事件" in prompt
    assert "茅台 2025 年报" in prompt


@pytest.mark.asyncio
async def test_dimension_d4_tavily_failure_does_not_block():
    """Tavily 抛异常 → 仅警告,继续走 LLM。"""
    em = _mock_adapter(_executives_a(), _hold_changes_a())
    llm = _mock_llm(_LLM_OK)
    tavily = MagicMock()
    tavily.search_with_cache = MagicMock(side_effect=RuntimeError("tavily 503"))

    dim, partial = await dimension_d4(_ref_a(), em_adapter=em, tavily=tavily, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert partial["management_rating"] == "合格"


@pytest.mark.asyncio
async def test_dimension_d4_only_tavily_no_executives_still_runs_llm():
    """无高管 + 无持股变动,但 Tavily 有内容 → 仍调 LLM,不直接降级。"""
    em = _mock_adapter([], [])
    llm = _mock_llm(_LLM_OK)
    tavily = MagicMock()
    tavily.search_with_cache = MagicMock(
        return_value={
            "answer": "x",
            "results": [{"title": "t", "url": "u", "content": "c"}],
        }
    )

    dim, _ = await dimension_d4(_ref_a(), em_adapter=em, tavily=tavily, llm=llm)

    assert not dim.narrative.startswith("⚠️")
    assert llm.complete.await_count == 1


# ===== mock alias =====


def test_mock_dimension_d4_is_real_implementation():
    from services.agent.core.qualitative.dimensions.d4 import (
        dimension_d4 as real,
        mock_dimension_d4 as mock,
    )

    assert mock is real
