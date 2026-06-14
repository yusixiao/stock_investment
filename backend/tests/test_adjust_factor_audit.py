"""前复权因子审计模块测试 — 幻灵拆股检测 + 重算。"""

from backend.adapters.adjust_factor_audit import (
    audit_factors,
    recompute_factors,
)


def _byd_like_records():
    """模拟 01211.HK 事故:2025 两次幻灵拆股(0.33≈3:1、0.167≈6:1)+ 末尾小额分红。"""
    return [
        ("2024-06-11", 0.054697),
        ("2025-06-10", 0.165860),
        ("2025-07-30", 0.995157),
        ("2026-06-11", 1.0),
    ]


def _byd_like_raw():
    """raw 价在两个幻灵日均无跳空(+2.6% / -5.8% 的正常波动)。"""
    return [
        ("2024-06-10", 80.0),
        ("2024-06-11", 81.0),
        ("2025-06-09", 132.2),
        ("2025-06-10", 135.6),  # +2.6%,绝非 3:1 拆股
        ("2025-07-29", 128.3),
        ("2025-07-30", 120.9),  # -5.8%,绝非 6:1 拆股
        ("2026-06-10", 100.0),
        ("2026-06-11", 99.5),
    ]


def test_detects_phantom_splits():
    events = audit_factors(_byd_like_records(), _byd_like_raw())
    by_date = {e.date: e for e in events}
    assert by_date["2025-06-10"].is_phantom is True
    assert by_date["2025-07-30"].is_phantom is True
    # 首事件 + 末尾小额分红不应被标记
    assert by_date["2024-06-11"].is_phantom is False
    assert by_date["2026-06-11"].is_phantom is False


def test_reconstructed_change_matches():
    events = audit_factors(_byd_like_records(), _byd_like_raw())
    by_date = {e.date: e for e in events}
    # change = prev_factor / factor
    assert abs(by_date["2025-06-10"].change - (0.054697 / 0.165860)) < 1e-6
    assert abs(by_date["2025-07-30"].change - (0.165860 / 0.995157)) < 1e-6


def test_recompute_flattens_phantom_jump():
    events = audit_factors(_byd_like_records(), _byd_like_raw())
    fixed = dict(recompute_factors(events))
    # 锚点保持
    assert abs(fixed["2026-06-11"] - 1.0) < 1e-9
    # 幻灵事件中性化后,2024→2026 因子不再有 18× 跳变(应全部 ~0.99 平稳)
    vals = [fixed[d] for d in ("2024-06-11", "2025-06-10", "2025-07-30", "2026-06-11")]
    assert max(vals) / min(vals) < 1.05  # 旧数据该比值 ~18


def test_legit_split_is_kept():
    """真实 4:1 拆股:factor_change=0.25 且 raw 同步跳空 → 必须保留。"""
    records = [
        ("2020-01-01", 0.25),
        ("2020-06-01", 1.0),
    ]
    raw = [
        ("2020-05-29", 400.0),
        ("2020-06-01", 100.0),  # 真实 4:1 跳空,raw_ratio=0.25
    ]
    events = audit_factors(records, raw)
    by_date = {e.date: e for e in events}
    assert by_date["2020-06-01"].is_phantom is False
    fixed = dict(recompute_factors(events))
    assert abs(fixed["2020-01-01"] - 0.25) < 1e-6  # 合法因子不动


def test_legit_consolidation_is_kept():
    """真实合股 1:10(reverse split):factor_change=10 且 raw 同步 ×10 → 保留。"""
    records = [
        ("2020-01-01", 10.0),
        ("2020-06-01", 1.0),
    ]
    raw = [
        ("2020-05-29", 1.0),
        ("2020-06-01", 10.0),  # raw_ratio=10
    ]
    events = audit_factors(records, raw)
    assert events[-1].is_phantom is False


def test_small_dividends_untouched():
    """普通分红(change≈0.97)低于 split_gate,不校验、不标记。"""
    records = [
        ("2020-01-01", 0.94),
        ("2021-01-01", 0.97),
        ("2022-01-01", 1.0),
    ]
    raw = [("2019-12-31", 50.0), ("2022-01-01", 52.0)]
    events = audit_factors(records, raw)
    assert all(not e.is_phantom for e in events)
    assert all("small" in e.reason or "base" in e.reason for e in events)


def test_unverifiable_large_change_kept():
    """大变动但无 raw 价可校验 → 保守保留。"""
    records = [("2020-01-01", 0.3), ("2020-06-01", 1.0)]
    raw = []  # 无 raw 数据
    events = audit_factors(records, raw)
    assert events[-1].is_phantom is False
    assert "unverifiable" in events[-1].reason


def test_empty_inputs():
    assert audit_factors([], []) == []
    assert recompute_factors([]) == []


def test_phantom_after_real_history_preserves_relative_dividends():
    """幻灵事件夹在合法小额分红之间:仅幻灵被展平,小额分红比例保留。"""
    records = [
        ("2019-01-01", 0.10),   # 由后续(含幻灵)累乘而来
        ("2020-01-01", 0.102),  # 小额分红
        ("2021-01-01", 0.34),   # 幻灵 3:1(change=0.102/0.34=0.3)
        ("2022-01-01", 1.0),
    ]
    raw = [
        ("2018-12-31", 10.0),
        ("2020-01-01", 10.2),
        ("2020-12-31", 11.0),
        ("2021-01-01", 11.1),   # 无跳空 → 幻灵
        ("2022-01-01", 12.0),
    ]
    events = audit_factors(records, raw)
    by_date = {e.date: e for e in events}
    assert by_date["2021-01-01"].is_phantom is True
    fixed = dict(recompute_factors(events))
    # 2021 幻灵展平后,2019→2022 不再有 ~3× 跳变
    assert fixed["2020-01-01"] / fixed["2022-01-01"] < 1.1
