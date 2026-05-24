"""§14 无风险利率 section 测试。

设计:
- 优先尝试从 akshare bond_china_yield 拉取最新 10Y 国债收益率
- akshare 在本环境会超时/失败,必须 mock
- 任何异常一律 fallback 到 RF_CHINA_10Y 常量(2026Q2 快照),不抛
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from services.agent.pipeline.phase1_data_pack.sections import s14_rf


class _Ref:
    code = "002594.SZ"
    name = "比亚迪"


def test_section_14_uses_akshare_when_available():
    """akshare 返回正常 DataFrame 时,使用最新一行的 10Y 收益率。"""
    fake_df = pd.DataFrame(
        {
            "日期": ["2026-05-20", "2026-05-21", "2026-05-22"],
            "中国国债收益率10年": [2.85, 2.91, 2.93],
        }
    )
    with patch.object(s14_rf, "_fetch_china_10y_yield", return_value=0.0293):
        out = s14_rf.build(_Ref())
    assert "## §14 无风险利率 Rf" in out
    assert "2.93%" in out
    assert "akshare" in out.lower() or "实时" in out


def test_section_14_falls_back_to_constant_on_exception():
    """akshare 抛异常 / 返回 None 时降级到常量,不传播。"""
    with patch.object(s14_rf, "_fetch_china_10y_yield", return_value=None):
        out = s14_rf.build(_Ref())
    assert "## §14 无风险利率 Rf" in out
    assert f"{s14_rf.RF_CHINA_10Y * 100:.2f}%" in out
    assert "快照" in out or "fallback" in out.lower() or "降级" in out


def test_section_14_fetcher_swallows_akshare_error():
    """_fetch_china_10y_yield 内部捕获所有异常,返回 None。"""

    def boom(*a, **kw):
        raise TimeoutError("akshare timeout")

    with patch("akshare.bond_china_yield", side_effect=boom):
        result = s14_rf._fetch_china_10y_yield()
    assert result is None
