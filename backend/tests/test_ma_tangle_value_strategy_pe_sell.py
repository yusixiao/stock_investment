"""MaTangleValueStrategy PE 两阶段卖出策略测试(2026-05-24 重构)。

新规格(替代旧的 MACD 周线触发):
- **Stage 1 触发**(每日):
  - 条件:当前 PE(TTM)> pe_sell_threshold(默认 30)
  - 操作:卖出**初始持仓的 15%**
  - 记录参考价 P_ref = 当日 daily bar 的 (high + low) / 2
- **Stage 2 触发**(每日,Stage 1 之后):
  - 条件:当日 daily close > P_ref * 1.05
  - 操作:卖出**初始持仓的 20%**(剩余 65% 持仓)
  - 触发后 stage=2,remove_target 防止再次选入

PE 缺失保守不卖。
"""

from __future__ import annotations

from typing import Any

from backend.tests.utils_test_helpers import MockContext
from strategies.examples.ma_tangle_value_strategy import MaTangleValueStrategy


# ===== 共用工具 =====


class _Pos:
    def __init__(self, shares: int):
        self.shares = shares


class _SellCtx(MockContext):
    """扩展 MockContext:支持 positions / remove_target。"""

    def __init__(self, *, positions: dict[str, int], current_date: str, **kw):
        super().__init__(current_date=current_date, **kw)
        self._positions = {sym: _Pos(n) for sym, n in positions.items()}
        self.removed_targets: list[str] = []

    def get_positions(self) -> dict[str, Any]:
        return self._positions

    def remove_target(self, sym: str) -> None:
        self.removed_targets.append(sym)


def _daily(close: float, high: float | None = None, low: float | None = None) -> dict:
    """构造单 symbol 的 daily price dict。默认 high=close+0.5 / low=close-0.5。"""
    h = close + 0.5 if high is None else high
    lo = close - 0.5 if low is None else low
    return {"X": {"daily": {"close": close, "high": h, "low": lo}}}


# ===== 1. 策略元信息 =====


def test_pe_sell_params_new_schema():
    """新参数表:pe_sell_enabled / threshold / stage1_pct / stage2_pct / breakout_pct。"""
    s = MaTangleValueStrategy()
    assert s.p.pe_sell_enabled is True
    assert s.p.pe_sell_threshold == 30.0
    assert s.p.pe_sell_stage1_pct == 0.15
    assert s.p.pe_sell_stage2_pct == 0.20
    assert s.p.pe_sell_breakout_pct == 0.05


def test_old_macd_sell_params_removed():
    """旧 macd_sell_* 参数全部废弃。"""
    s = MaTangleValueStrategy()
    for key in (
        "macd_sell_enabled",
        "macd_sell_stage1_pct",
        "macd_sell_stage2_pct",
        "macd_sell_breakout_pct",
        "macd_sell_pe_min",
        "macd_sell_batches",
    ):
        assert key not in s.params, f"旧参数 {key} 应已删除"


# ===== 2. Stage 1:PE > 阈值 → 卖 15% =====


def test_stage1_does_nothing_when_pe_below_threshold():
    """PE=20 ≤ 30 → 不卖。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        valuation={"X": {"peTTM": 20.0}},
        price=_daily(close=100.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
    assert "X" not in s._sell_state


def test_stage1_first_trigger_sells_15pct_and_records_pref():
    """PE=35 > 30 → 卖 150 股(15%);P_ref = (160 + 158) / 2 = 159。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        valuation={"X": {"peTTM": 35.0}},
        price=_daily(close=159.0, high=160.0, low=158.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150)]
    assert ctx.removed_targets == []
    state = s._sell_state["X"]
    assert state["stage"] == 1
    assert state["initial_shares"] == 1000
    assert state["p_ref"] == 159.0


def test_stage1_only_triggers_once():
    """Stage 1 触发后 stage 进 1,后续 on_sell 走 stage 2 分支(close 未突破→不动)。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        valuation={"X": {"peTTM": 35.0}},
        price=_daily(close=159.0, high=160.0, low=158.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    s.on_sell(ctx)
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150)]


def test_stage1_disabled_by_param():
    """pe_sell_enabled=False → 不卖。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        valuation={"X": {"peTTM": 50.0}},
        price=_daily(close=100.0),
    )
    s = MaTangleValueStrategy(param_overrides={"pe_sell_enabled": False})
    s.on_sell(ctx)
    assert ctx.orders == []


def test_stage1_no_position_skipped():
    """shares=0 → 跳过。"""
    ctx = _SellCtx(
        positions={"X": 0},
        current_date="2024-12-06",
        valuation={"X": {"peTTM": 50.0}},
        price=_daily(close=100.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []


def test_stage1_pe_missing_skipped():
    """PE 缺失 → 保守不卖。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        # 不传 valuation
        price=_daily(close=100.0),
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
    assert "X" not in s._sell_state


def test_stage1_no_daily_bar_skipped():
    """无 daily price → 取不到 P_ref,跳过。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        valuation={"X": {"peTTM": 50.0}},
        # 不传 price
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
    assert "X" not in s._sell_state


def test_stage1_threshold_overridable():
    """参数覆盖 pe_sell_threshold=15 → PE=20 也能触发。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        valuation={"X": {"peTTM": 20.0}},
        price=_daily(close=100.0, high=101.0, low=99.0),
    )
    s = MaTangleValueStrategy(param_overrides={"pe_sell_threshold": 15.0})
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150)]
    assert s._sell_state["X"]["stage"] == 1
    assert s._sell_state["X"]["p_ref"] == 100.0


# ===== 3. Stage 2:Stage 1 之后,daily close > P_ref * 1.05 =====


def test_stage2_triggers_when_close_breaks_pref_by_5pct():
    """P_ref=159,close=167 (>159*1.05=166.95) → 卖 200 股 + remove_target。"""
    s = MaTangleValueStrategy()
    s._sell_state["X"] = {
        "stage": 1,
        "initial_shares": 1000,
        "p_ref": 159.0,
    }
    ctx = _SellCtx(
        positions={"X": 850},  # 1000 - 150
        current_date="2025-01-15",
        price={"X": {"daily": {"close": 167.0, "high": 168.0, "low": 166.0}}},
    )
    s.on_sell(ctx)
    assert ctx.orders == [("X", -200)]
    assert s._sell_state["X"]["stage"] == 2
    assert ctx.removed_targets == ["X"]


def test_stage2_no_trigger_when_below_threshold():
    """close=166.5 < P_ref*1.05=166.95 → 不卖。"""
    s = MaTangleValueStrategy()
    s._sell_state["X"] = {
        "stage": 1,
        "initial_shares": 1000,
        "p_ref": 159.0,
    }
    ctx = _SellCtx(
        positions={"X": 850},
        current_date="2025-01-15",
        price={"X": {"daily": {"close": 166.5, "high": 167.0, "low": 166.0}}},
    )
    s.on_sell(ctx)
    assert ctx.orders == []
    assert s._sell_state["X"]["stage"] == 1


def test_stage2_only_triggers_once():
    """Stage 2 触发后,即使后续 close 更高也不再卖。"""
    s = MaTangleValueStrategy()
    s._sell_state["X"] = {
        "stage": 1,
        "initial_shares": 1000,
        "p_ref": 159.0,
    }
    ctx = _SellCtx(
        positions={"X": 850},
        current_date="2025-01-15",
        price={"X": {"daily": {"close": 170.0, "high": 171.0, "low": 169.0}}},
    )
    s.on_sell(ctx)
    assert len(ctx.orders) == 1
    # 第 2 天再次调用,价格更高
    ctx.current_date = "2025-01-16"
    ctx._price = {"X": {"daily": {"close": 180.0, "high": 181.0, "low": 179.0}}}
    s.on_sell(ctx)
    assert len(ctx.orders) == 1


# ===== 4. 全生命周期 =====


def test_full_lifecycle_stage1_then_stage2():
    """Stage 1(PE 触发卖 150)→ 多日观察 → Stage 2(突破卖 200),总 35% 卖出。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        valuation={"X": {"peTTM": 35.0}},
        price=_daily(close=159.0, high=160.0, low=158.0),
    )
    s = MaTangleValueStrategy()

    # Stage 1 触发:卖 150,P_ref=159
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150)]
    assert s._sell_state["X"]["p_ref"] == 159.0

    # 模拟持仓减少
    ctx._positions["X"].shares = 850

    # 第 2 天 close=160(< 166.95)→ 不卖
    ctx.current_date = "2024-12-07"
    ctx._price = {"X": {"daily": {"close": 160.0, "high": 161.0, "low": 159.0}}}
    s.on_sell(ctx)
    assert len(ctx.orders) == 1

    # 第 N 天 close=170(> 166.95)→ Stage 2 卖 200
    ctx.current_date = "2025-02-10"
    ctx._price = {"X": {"daily": {"close": 170.0, "high": 171.0, "low": 169.0}}}
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150), ("X", -200)]
    assert s._sell_state["X"]["stage"] == 2
    assert ctx.removed_targets == ["X"]
    total_sold = -sum(o[1] for o in ctx.orders)
    assert total_sold == 350  # 35%
