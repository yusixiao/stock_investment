"""§16 同业可比公司 section 测试。

实现要点:
- 通过 stock_index.get_industry(code) 拿到当前股票行业
- 通过 stock_index.get_peers_by_industry(industry, exclude_code, limit) 找同行
- 对每个 peer 调 store.query_financial(table='indicator', years=1) 取最近 1 年关键比率
- 拼成 markdown 表
- 任何缺失环节(无行业 / 无同行 / store 异常)优雅降级
"""

from __future__ import annotations

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import (
    s16_peers_placeholder as s16,
)


class _Ref:
    code = "002594.SZ"
    name = "比亚迪"


def _peer(code, name, industry="C36汽车制造业"):
    p = MagicMock()
    p.code = code
    p.name = name
    p.industry = industry
    return p


def test_section_16_no_industry_returns_placeholder():
    """stock_index.get_industry 返回 None 时,输出占位说明而非崩溃。"""
    si = MagicMock()
    si.get_industry.return_value = None
    store = MagicMock()
    out = s16.build(_Ref(), store=store, stock_index=si, indicators=None)
    assert "## §16 同业可比公司" in out
    assert "行业" in out and ("缺失" in out or "未提供" in out or "无法" in out)


def test_section_16_no_peers_returns_message():
    """有行业但同行为空时,提示无同行。"""
    si = MagicMock()
    si.get_industry.return_value = "C36汽车制造业"
    si.get_peers_by_industry.return_value = []
    store = MagicMock()
    out = s16.build(_Ref(), store=store, stock_index=si, indicators=None)
    assert "## §16 同业可比公司" in out
    assert "C36汽车制造业" in out
    assert "无同行" in out or "未找到" in out or "0 家" in out


def test_section_16_renders_peers_table():
    """正常路径:渲染同行 PE/PB/ROE/毛利率对比表。"""
    si = MagicMock()
    si.get_industry.return_value = "C36汽车制造业"
    si.get_peers_by_industry.return_value = [
        _peer("000625.SZ", "长安汽车"),
        _peer("601238.SH", "广汽集团"),
    ]

    # store.query_financial 按 code 返回不同 indicator 数据
    def _query(code, table, years):
        assert table == "indicator"
        if code == "002594.SZ":
            return [
                {
                    "REPORT_DATE": "2025-12-31",
                    "ROEJQ": 18.2,
                    "GROSSPROFIT_MARGIN": 22.5,
                    "NETPROFIT_MARGIN": 5.8,
                    "DEBT_ASSET_RATIO": 70.0,
                }
            ]
        if code == "000625.SZ":
            return [
                {
                    "REPORT_DATE": "2025-12-31",
                    "ROEJQ": 9.1,
                    "GROSSPROFIT_MARGIN": 15.0,
                    "NETPROFIT_MARGIN": 3.2,
                    "DEBT_ASSET_RATIO": 65.0,
                }
            ]
        if code == "601238.SH":
            return [
                {
                    "REPORT_DATE": "2025-12-31",
                    "ROEJQ": 4.5,
                    "GROSSPROFIT_MARGIN": 10.5,
                    "NETPROFIT_MARGIN": 2.1,
                    "DEBT_ASSET_RATIO": 55.0,
                }
            ]
        return []

    store = MagicMock()
    store.query_financial_for_section.side_effect = _query

    out = s16.build(_Ref(), store=store, stock_index=si, indicators=None)
    assert "## §16 同业可比公司" in out
    assert "C36汽车制造业" in out
    # 行业 + 自己 + 2 个同行,表里都应出现
    assert "比亚迪" in out and "002594.SZ" in out
    assert "长安汽车" in out and "000625.SZ" in out
    assert "广汽集团" in out and "601238.SH" in out
    # 数据值
    assert "18.2" in out  # 比亚迪 ROE
    assert "9.10" in out or "9.1" in out  # 长安 ROE


def test_section_16_handles_store_exception_gracefully():
    """store 抛异常时降级,不传播。"""
    si = MagicMock()
    si.get_industry.return_value = "C36汽车制造业"
    si.get_peers_by_industry.return_value = [_peer("000625.SZ", "长安汽车")]
    store = MagicMock()
    store.query_financial_for_section.side_effect = RuntimeError("duckdb boom")

    out = s16.build(_Ref(), store=store, stock_index=si, indicators=None)
    assert "## §16 同业可比公司" in out
    # 至少包含表头或行业信息,不崩溃
    assert "C36汽车制造业" in out
