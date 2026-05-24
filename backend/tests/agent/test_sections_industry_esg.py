"""§8 行业 + §10 ESG section 渲染测试。"""

from __future__ import annotations

from types import SimpleNamespace

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import (
    s08_industry,
    s10_esg,
)


class _StockIndex:
    def __init__(self, industry=None):
        self._industry = industry

    def get_industry(self, code):
        return self._industry


class _Tavily:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[tuple] = []

    def search_with_cache(self, code, section, query, **kw):
        self.calls.append((code, section, query))
        return self.payload


def _ref():
    return SimpleNamespace(code="002594.SZ", name="比亚迪", market="A")


# ---------- §8 ----------


def test_s08_with_industry_and_tavily():
    payload = {
        "answer": "新能源汽车行业景气度高",
        "results": [
            {
                "title": "新能源车补贴新政",
                "content": "财政部发文延续新能源汽车购置税减免...",
                "url": "https://example.com/a",
            },
            {
                "title": "电池技术替代风险",
                "content": "固态电池路线...",
                "url": "https://example.com/b",
            },
        ],
    }
    tavily = _Tavily(payload)
    out = s08_industry.build(
        _ref(),
        store=None,
        stock_index=_StockIndex(industry="汽车整车"),
        indicators=None,
        tavily=tavily,
    )
    assert "§8" in out
    assert "汽车整车" in out
    assert "新能源车补贴新政" in out
    assert "https://example.com/a" in out
    assert tavily.calls
    assert "汽车整车" in tavily.calls[0][2]


def test_s08_no_industry_degrades():
    out = s08_industry.build(
        _ref(),
        store=None,
        stock_index=_StockIndex(industry=None),
        indicators=None,
        tavily=_Tavily({"results": []}),
    )
    assert "§8" in out
    assert "行业信息缺失" in out or "数据待补" in out


def test_s08_no_tavily_degrades():
    out = s08_industry.build(
        _ref(),
        store=None,
        stock_index=_StockIndex(industry="汽车整车"),
        indicators=None,
        tavily=None,
    )
    assert "§8" in out
    assert "汽车整车" in out
    assert "数据待补" in out or "未启用" in out


def test_s08_tavily_returns_none_degrades():
    """无 API key 或 search 失败时 search_with_cache 返回 None。"""

    class _NullTavily:
        def search_with_cache(self, *a, **k):
            return None

    out = s08_industry.build(
        _ref(),
        store=None,
        stock_index=_StockIndex(industry="汽车整车"),
        indicators=None,
        tavily=_NullTavily(),
    )
    assert "§8" in out
    assert "数据待补" in out or "未启用" in out


# ---------- §10 ----------


def test_s10_with_tavily_renders_events():
    payload = {
        "answer": "近期未发现重大处罚",
        "results": [
            {
                "title": "比亚迪召回部分车型",
                "content": "因刹车系统隐患召回 2.7 万辆...",
                "url": "https://example.com/recall",
            }
        ],
    }
    out = s10_esg.build(
        _ref(),
        store=None,
        stock_index=None,
        indicators=None,
        tavily=_Tavily(payload),
    )
    assert "§10" in out
    assert "召回" in out
    assert "https://example.com/recall" in out


def test_s10_no_tavily_degrades():
    out = s10_esg.build(
        _ref(),
        store=None,
        stock_index=None,
        indicators=None,
        tavily=None,
    )
    assert "§10" in out
    assert "数据待补" in out or "未启用" in out


def test_s10_empty_results_says_no_events():
    out = s10_esg.build(
        _ref(),
        store=None,
        stock_index=None,
        indicators=None,
        tavily=_Tavily({"answer": "无", "results": []}),
    )
    assert "§10" in out
    # 没有事件应当明确告知,而不是空表
    assert "未检索到" in out or "无负面" in out or "无重大" in out
