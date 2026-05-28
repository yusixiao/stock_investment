"""L3 仓位矩阵单测(strategies/utils/conservative.py)。

CPA 原口径 4 档:f(r_pct, credibility, trap_rating) → tier ∈ {full, p70, observe, skip}

阈值默认:
  threshold_pct = 5.2(A 股 II + 安全边际 0.5)
  full_bonus_pct = 1.5(对齐 CPA 原文 KK ≥ 1.5pct)
  → full / p70 阈值 = 5.2 + 1.5 = 6.7pct
"""

from __future__ import annotations

from tests.utils_test_helpers import MockContext

from strategies.utils.conservative import (
    TIER_PCT,
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
    """R < 5.2 → skip(KK<0,无论 cred / trap)。"""
    assert compute_position_tier(5.0, "high", "low") == "skip"
    assert compute_position_tier(3.0, "mid", "low") == "skip"
    assert compute_position_tier(0.0, "high", "low") == "skip"


def test_trap_high_observe():
    """R 达标 + cred 非 low + trap=high → observe(避免重仓陷阱)。"""
    assert compute_position_tier(20.0, "high", "high") == "observe"
    assert compute_position_tier(8.0, "mid", "high") == "observe"
    assert compute_position_tier(5.5, "high", "high") == "observe"


def test_full_tier():
    """R ≥ 6.7(KK≥1.5)+ cred=high + trap=low → full。"""
    assert compute_position_tier(6.7, "high", "low") == "full"
    assert compute_position_tier(15.0, "high", "low") == "full"
    assert compute_position_tier(100.0, "high", "low") == "full"


def test_p70_high_cred_mid_trap():
    """R ≥ 6.7 + cred=high + trap=mid → p70。"""
    assert compute_position_tier(6.7, "high", "mid") == "p70"
    assert compute_position_tier(20.0, "high", "mid") == "p70"


def test_p70_mid_cred_low_trap():
    """R ≥ 6.7 + cred=mid + trap=low → p70。"""
    assert compute_position_tier(6.7, "mid", "low") == "p70"
    assert compute_position_tier(20.0, "mid", "low") == "p70"


def test_observe_kk_below_1_5_high_cred_low_trap():
    """R ∈ [5.2, 6.7) + cred=high + trap=low → observe(KK 0~1.5pct,用户口径)。"""
    assert compute_position_tier(5.2, "high", "low") == "observe"
    assert compute_position_tier(6.0, "high", "low") == "observe"
    assert compute_position_tier(6.69, "high", "low") == "observe"


def test_observe_kk_below_1_5_mid_cred():
    """R ∈ [5.2, 6.7) + cred=mid → observe(KK 0~1.5pct)。"""
    assert compute_position_tier(5.2, "mid", "low") == "observe"
    assert compute_position_tier(6.0, "mid", "low") == "observe"


def test_observe_high_r_mid_cred_mid_trap():
    """R ≥ 6.7 + cred=mid + trap=mid → observe(没有 high 维度,不进 p70)。"""
    assert compute_position_tier(7.0, "mid", "mid") == "observe"
    assert compute_position_tier(20.0, "mid", "mid") == "observe"


def test_observe_high_r_high_cred_high_trap():
    """R ≥ 6.7 + cred=high + trap=high → observe(trap=high 优先级最高)。"""
    assert compute_position_tier(6.7, "high", "high") == "observe"
    assert compute_position_tier(20.0, "high", "high") == "observe"


def test_custom_thresholds():
    """自定义 threshold_pct 与 full_bonus_pct。"""
    # threshold_pct=10,full_bonus_pct=5 → full/p70 阈值 ≥ 15
    assert (
        compute_position_tier(
            15.0, "high", "low", threshold_pct=10.0, full_bonus_pct=5.0
        )
        == "full"
    )
    # 14.9 < 15 → KK 0~5,observe
    assert (
        compute_position_tier(
            14.9, "high", "low", threshold_pct=10.0, full_bonus_pct=5.0
        )
        == "observe"
    )
    # 9.9 < 10 → KK<0 → skip
    assert (
        compute_position_tier(
            9.9, "high", "low", threshold_pct=10.0, full_bonus_pct=5.0
        )
        == "skip"
    )


def test_invalid_credibility_treated_as_mid():
    """未知 credibility 字符串 → 退化为 mid;高 R+mid+low → p70。"""
    assert compute_position_tier(20.0, "unknown", "low") == "p70"


def test_tier_pct_constants():
    """TIER_PCT 常量与 CPA 原口径对齐。"""
    assert TIER_PCT["full"] == 1.0
    assert TIER_PCT["p70"] == 0.7
    assert TIER_PCT["observe"] == 0.0
    assert TIER_PCT["skip"] == 0.0


# ---------- record_position_tier 批量集成 ----------


def test_record_position_tier_basic():
    """批量记录 + 默认筛除 skip / observe(保留 full / p70)。"""
    ctx = MockContext()
    # A: full(R≥6.7 + high + low)
    ctx.record_factor("A", "R_pct", 8.0)
    ctx.record_factor("A", "credibility_rating", "high")
    ctx.record_factor("A", "trap_rating", "low")

    # B: observe(R 5.2~6.7,KK 0~1.5)
    ctx.record_factor("B", "R_pct", 6.0)
    ctx.record_factor("B", "credibility_rating", "high")
    ctx.record_factor("B", "trap_rating", "low")

    # C: skip(cred=low)
    ctx.record_factor("C", "R_pct", 8.0)
    ctx.record_factor("C", "credibility_rating", "low")
    ctx.record_factor("C", "trap_rating", "low")

    # D: observe(trap=high)
    ctx.record_factor("D", "R_pct", 8.0)
    ctx.record_factor("D", "credibility_rating", "high")
    ctx.record_factor("D", "trap_rating", "high")

    # E: p70(R≥6.7 + mid + low)
    ctx.record_factor("E", "R_pct", 8.0)
    ctx.record_factor("E", "credibility_rating", "mid")
    ctx.record_factor("E", "trap_rating", "low")

    pool = record_position_tier(ctx, ["A", "B", "C", "D", "E"])
    assert "A" in pool  # full
    assert "E" in pool  # p70
    assert "B" not in pool  # observe(KK<1.5)
    assert "C" not in pool  # skip
    assert "D" not in pool  # observe(trap=high)
    assert ctx.get_factors("A")["position_tier"] == "full"
    assert ctx.get_factors("B")["position_tier"] == "observe"
    assert ctx.get_factors("C")["position_tier"] == "skip"
    assert ctx.get_factors("D")["position_tier"] == "observe"
    assert ctx.get_factors("E")["position_tier"] == "p70"


def test_record_position_tier_include_observe():
    """include_observe=True → 把 observe 也放回池子(只观察不买)。"""
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
