"""R19: 个股波动率加权(_compute_weights)单测。

锁定 equal/invvol/invvar 三方案 + 单股封顶重分配 + 缺失波动率回填的行为,
确保权重始终归一化(sum=1)且 PIT(波动率仅由 screen 阶段历史收益派生)。
"""
import pytest

from services.backtest.strategies.deployed.hk_garp_strategy import HkGarpStrategy


def _strat(scheme, cap=2.5, top_n=12, vols=None):
    s = HkGarpStrategy(
        {"weight_scheme": scheme, "weight_cap_mult": cap, "top_n": top_n}
    )
    s._sym_vol = vols or {}
    return s


def test_equal_weight_is_uniform():
    s = _strat("equal")
    w = s._compute_weights(["a", "b", "c", "d"])
    assert all(abs(v - 0.25) < 1e-9 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_empty_target_returns_empty():
    s = _strat("invvol")
    assert s._compute_weights([]) == {}


def test_invvol_lower_vol_gets_higher_weight():
    vols = {"a": 0.01, "b": 0.02, "c": 0.04, "d": 0.08}
    s = _strat("invvol", cap=0, vols=vols)
    w = s._compute_weights(list(vols))
    # 单调:波动率越低权重越高
    assert w["a"] > w["b"] > w["c"] > w["d"]
    # 1/0.01:1/0.02:1/0.04:1/0.08 = 8:4:2:1 → 0.5333/0.2667/0.1333/0.0667
    assert abs(w["a"] - 8 / 15) < 1e-6
    assert abs(w["d"] - 1 / 15) < 1e-6
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_invvar_more_concentrated_than_invvol():
    vols = {"a": 0.01, "b": 0.02, "c": 0.04, "d": 0.08}
    wv = _strat("invvol", cap=0, vols=vols)._compute_weights(list(vols))
    wq = _strat("invvar", cap=0, vols=vols)._compute_weights(list(vols))
    # 反方差对低波动股加权更激进
    assert wq["a"] > wv["a"]
    assert abs(sum(wq.values()) - 1.0) < 1e-9


def test_cap_not_binding_when_below_limit():
    # eq=0.25, cap=2.5×=0.625;最大权重 0.533 < cap → 不变
    vols = {"a": 0.01, "b": 0.02, "c": 0.04, "d": 0.08}
    s = _strat("invvol", cap=2.5, vols=vols)
    w = s._compute_weights(list(vols))
    assert max(w.values()) <= 0.625 + 1e-9
    assert abs(w["a"] - 8 / 15) < 1e-6


def test_cap_binding_redistributes_excess():
    # 紧封顶 cap=1.5×eq=0.375;a 原 0.533 被削到 0.375,超额分给其余
    vols = {"a": 0.01, "b": 0.02, "c": 0.04, "d": 0.08}
    s = _strat("invvol", cap=1.5, vols=vols)
    w = s._compute_weights(list(vols))
    assert max(w.values()) <= 0.375 + 1e-9
    assert abs(w["a"] - 0.375) < 1e-6
    assert abs(sum(w.values()) - 1.0) < 1e-9
    # 重分配后其余股票权重应上升
    assert w["d"] > 1 / 15


def test_missing_vol_filled_with_mean():
    # c 无波动率 → 用 a,b 的风险倒数均值回填
    s = _strat("invvol", cap=0, vols={"a": 0.02, "b": 0.04})
    w = s._compute_weights(["a", "b", "c"])
    # raw: a=50, b=25, fill=37.5 → 归一 0.4444/0.2222/0.3333
    assert abs(w["a"] - 50 / 112.5) < 1e-6
    assert abs(w["c"] - 37.5 / 112.5) < 1e-6
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_no_vol_data_falls_back_to_equal():
    # invvol 但 _sym_vol 全空 → 退化等权
    s = _strat("invvol", cap=2.5, vols={})
    w = s._compute_weights(["a", "b", "c"])
    assert all(abs(v - 1 / 3) < 1e-9 for v in w.values())


def test_zero_or_negative_vol_treated_as_missing():
    s = _strat("invvol", cap=0, vols={"a": 0.02, "b": 0.0, "c": -0.01})
    w = s._compute_weights(["a", "b", "c"])
    # b,c 非法 → 回填为 a 的权重(唯一已知)→ 三者相等
    assert all(abs(v - 1 / 3) < 1e-9 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-9
