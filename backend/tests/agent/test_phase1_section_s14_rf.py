"""§14 无风险利率 section 测试(2026-05-24:移除 akshare 依赖,改纯常量)。"""

from __future__ import annotations

from services.agent.pipeline.phase1_data_pack.sections import s14_rf


class _Ref:
    code = "002594.SZ"
    name = "比亚迪"


def test_section_14_uses_constant():
    """build() 返回 markdown,引用 RF_CHINA_10Y 常量。"""
    out = s14_rf.build(_Ref())
    assert "## §14 无风险利率 Rf" in out
    assert f"{s14_rf.RF_CHINA_10Y * 100:.2f}%" in out
    assert "常量快照" in out


def test_rf_china_10y_is_reasonable():
    """常量值应在合理范围(1% ~ 6%)。"""
    assert 0.01 <= s14_rf.RF_CHINA_10Y <= 0.06
