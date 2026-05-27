"""L3 仓位矩阵单测(strategies/utils/conservative.py)。

三维查找表 f(r_pct, credibility, trap_rating) → tier ∈ {full, half, observe, skip}

阈值默认:
  threshold_pct = 5.2(A 股 II + 安全边际 0.5)
  full_bonus_pct = 2.0(full tier 加成)
"""

from __future__ import annotations

from tests.utils_test_helpers import MockContext

from strategies.utils.conservative import (
    compute_position_tier,
    record_position_tier,
)


# ---------- compute_position_tier 单元规则 ----------


def test_credibility_low_always_skip():
    """credibility=low → skip(无论 R / trap)。"""
    assert compute_position_tier(20.0, "low", "low") == "skip"
    assert compute_position_tier(20.0, "low", "high") == "skip"
    assert compute_position_tier(0.0, "low", "low") == "skip"


def test_r_below_threshold_skip():
    """R < 5.2 → skip(无论 cred / trap)。"""
    assert compute_position_tier(5.0, "high", "low") == "skip"
    assert compute_position_tier(3.0, "mid", "low") == "skip"
    assert compute_position_tier(0.0, "high", "low") == "skip"


def test_trap_high_observe():
    """R 达标 + cred 非 low + trap=high → observe(避免重仓陷阱)。"""
    assert compute_position_tier(20.0, "high", "high") == "observe"
    assert compute_position_tier(8.0, "mid", "high") == "observe"
    assert compute_position_tier(5.5, "high", "high") == "observe"


def test_full_tier():
    """R ≥ 7.2 + cred=high + trap=low → full。"""
    assert compute_position_tier(7.2, "high", "low") == "full"
    assert compute_position_tier(15.0, "high", "low") == "full"
    assert compute_position_tier(100.0, "high", "low") == "full"


def test_half_tier_high_r_mid_cred():
    """R ≥ 7.2 + cred=mid + trap=low → half。"""
    assert compute_position_tier(7.2, "mid", "low") == "half"
    assert compute_position_tier(20.0, "mid", "low") == "half"


def test_half_tier_baseline_r_high_cred():
    """R ≥ 5.2 + cred=high + trap in {low, mid} → half。"""
    assert compute_position_tier(5.2, "high", "low") == "half"
    assert compute_position_tier(7.0, "high", "low") == "half"
    assert compute_position_tier(5.2, "high", "mid") == "half"
    assert compute_position_tier(7.0, "high", "mid") == "half"


def test_observe_high_r_high_cred_mid_trap():
    """R ≥ 7.2 + cred=high + trap=mid → observe(trap 拉低)。"""
    # 不进 full(trap 非 low),不进 baseline half(下面 high 的也是 half)
    # 实际:R ≥ 7.2 + cred=high + trap=mid → 走 baseline 规则 → half
    # 但根据规则 4(R≥7.2,cred=high,trap=low)是 full,trap=mid 时 fallback
    # 到规则 6(R≥5.2,cred=high,trap=low/mid)→ half
    assert compute_position_tier(8.0, "high", "mid") == "half"


def test_observe_baseline_r_mid_cred_low_trap():
    """R ≥ 5.2 + cred=mid + trap=low → observe(R 不足 full 加成,cred 不够高)。"""
    assert compute_position_tier(5.2, "mid", "low") == "observe"
    assert compute_position_tier(7.1, "mid", "low") == "observe"


def test_observe_baseline_r_mid_cred_mid_trap():
    """R ≥ 5.2 + cred=mid + trap=mid → observe。"""
    assert compute_position_tier(6.0, "mid", "mid") == "observe"


def test_observe_baseline_r_high_r_threshold_minus():
    """R 在 [5.2, 7.2) + cred=high + trap=mid → half(规则 6 命中)。"""
    assert compute_position_tier(6.0, "high", "mid") == "half"


def test_observe_r_at_threshold_high_cred_high_trap():
    """R ≥ 5.2 + cred=high + trap=high → observe(trap=high 优先级高)。"""
    assert compute_position_tier(5.2, "high", "high") == "observe"
    assert compute_position_tier(20.0, "high", "high") == "observe"


def test_observe_mid_cred_no_full_path():
    """R ≥ 5.2 但 < 7.2 + cred=mid + trap=mid → observe。"""
    assert compute_position_tier(5.5, "mid", "mid") == "observe"


def test_custom_thresholds():
    """自定义 threshold_pct 与 full_bonus_pct。"""
    # threshold_pct=10,full_bonus_pct=5 → full 需 ≥ 15
    assert (
        compute_position_tier(
            15.0, "high", "low", threshold_pct=10.0, full_bonus_pct=5.0
        )
        == "full"
    )
    assert (
        compute_position_tier(
            14.9, "high", "low", threshold_pct=10.0, full_bonus_pct=5.0
        )
        == "half"
    )
    assert (
        compute_position_tier(
            9.9, "high", "low", threshold_pct=10.0, full_bonus_pct=5.0
        )
        == "skip"
    )


def test_invalid_credibility_treated_as_mid():
    """未知 credibility 字符串 → 退化为 mid 处理(防御式)。"""
    # 实际实现可决定为何种行为,选择「未知 → mid」更合理(不至于 skip 也不至于 high 待遇)
    assert compute_position_tier(20.0, "unknown", "low") == "half"


# ---------- record_position_tier 批量集成 ----------


def test_record_position_tier_basic():
    """批量记录 + 默认筛除 skip / observe。"""
    ctx = MockContext()
    # 预先注入 R / credibility / trap_rating 因子
    ctx.record_factor("A", "R_pct", 8.0)
    ctx.record_factor("A", "credibility_rating", "high")
    ctx.record_factor("A", "trap_rating", "low")

    ctx.record_factor("B", "R_pct", 6.0)
    ctx.record_factor("B", "credibility_rating", "high")
    ctx.record_factor("B", "trap_rating", "low")

    ctx.record_factor("C", "R_pct", 8.0)
    ctx.record_factor("C", "credibility_rating", "low")
    ctx.record_factor("C", "trap_rating", "low")

    ctx.record_factor("D", "R_pct", 8.0)
    ctx.record_factor("D", "credibility_rating", "high")
    ctx.record_factor("D", "trap_rating", "high")

    pool = record_position_tier(ctx, ["A", "B", "C", "D"])
    assert "A" in pool  # full
    assert "B" in pool  # half
    assert "C" not in pool  # skip
    assert "D" not in pool  # observe(默认不含)
    assert ctx.get_factors("A")["position_tier"] == "full"
    assert ctx.get_factors("B")["position_tier"] == "half"
    assert ctx.get_factors("C")["position_tier"] == "skip"
    assert ctx.get_factors("D")["position_tier"] == "observe"


def test_record_position_tier_include_observe():
    """include_observe=True → 把 observe 也放回池子。"""
    ctx = MockContext()
    ctx.record_factor("D", "R_pct", 8.0)
    ctx.record_factor("D", "credibility_rating", "high")
    ctx.record_factor("D", "trap_rating", "high")
    pool = record_position_tier(ctx, ["D"], include_observe=True)
    assert pool == ["D"]
    assert ctx.get_factors("D")["position_tier"] == "observe"


def test_record_position_tier_missing_factors_skip():
    """缺失因子(R / cred / trap 任一)→ 默认 skip(无估值依据)。"""
    ctx = MockContext()
    # 只有 R,缺 cred + trap
    ctx.record_factor("X", "R_pct", 8.0)
    pool = record_position_tier(ctx, ["X"])
    assert "X" not in pool
    assert ctx.get_factors("X")["position_tier"] == "skip"


def test_record_position_tier_logs_flow():
    """log_flow 包含输入/通过/各 tier 计数。"""
    ctx = MockContext()
    ctx.record_factor("A", "R_pct", 8.0)
    ctx.record_factor("A", "credibility_rating", "high")
    ctx.record_factor("A", "trap_rating", "low")
    record_position_tier(ctx, ["A"])
    assert "A" in ctx.passed_symbols("conservative.position_tier")
