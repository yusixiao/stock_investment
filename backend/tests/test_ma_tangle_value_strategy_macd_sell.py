"""MaTangleValueStrategy MACD 两阶段卖出策略测试(2026-05-24 重构)。

新规格(替代旧的 4 批 25% 等量分批):
- **Stage 1 触发**(每周一次,周线 cadence):
  - 条件:本周 weekly macd_hist < 上周 weekly macd_hist(动能减弱)
  - 操作:卖出**初始持仓的 15%**
  - 记录参考价 P_ref = 当周 weekly bar 的 (high + low) / 2
- **Stage 2 触发**(每日,Stage 1 之后):
  - 条件:当日 daily close > P_ref * 1.05(突破回升 5%)
  - 操作:卖出**初始持仓的 20%**(剩余 65% 持仓)
  - 触发后不再判定(state.stage = 2),并 remove_target 防止重新选入

Helper 行为(实测,固化在测试 fixture 里):
- 单调上升收盘价 → 末尾两根 weekly hist 严格下降(动能减弱)→ 触发 Stage 1
- 单调下降收盘价 → 末尾两根 weekly hist 严格上升(动能恢复)→ 不触发 Stage 1
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


def _bars(closes: list[float], hl_spread: float = 1.0) -> list[dict]:
    """填 weekly bars。high = close + hl_spread/2,low = close - hl_spread/2。"""
    out = []
    for i, c in enumerate(closes):
        out.append(
            {
                "date": f"2024-{(i // 4) + 1:02d}-{((i % 4) * 7) + 1:02d}",
                "open": c,
                "high": c + hl_spread / 2,
                "low": c - hl_spread / 2,
                "close": c,
                "volume": 1000.0,
                "amount": c * 1000.0,
            }
        )
    return out


def _bars_hist_falling() -> list[dict]:
    """单调上升 closes → 末尾两根 hist 严格下降 → 触发 Stage 1。"""
    return _bars([100.0 + i * 1.0 for i in range(60)])


def _bars_hist_rising() -> list[dict]:
    """单调下降 closes → 末尾两根 hist 严格上升 → 不触发 Stage 1。"""
    return _bars([200.0 - i * 1.0 for i in range(60)])


# ===== 1. 策略元信息 =====


def test_macd_sell_params_new_schema():
    """新参数表:enabled / stage1_pct / stage2_pct / breakout_pct,旧 batches 已删除。"""
    s = MaTangleValueStrategy()
    assert s.p.macd_sell_enabled is True
    assert s.p.macd_sell_stage1_pct == 0.15
    assert s.p.macd_sell_stage2_pct == 0.20
    assert s.p.macd_sell_breakout_pct == 0.05
    # 旧参数应当不再存在
    assert "macd_sell_batches" not in s.params


def test_old_clearance_sell_params_removed():
    s = MaTangleValueStrategy()
    assert "sell_pe_pb_max" not in s.params
    assert "sell_below_ma" not in s.params


# ===== 2. Stage 1:MACD 周线下降 → 卖 15% =====


def test_stage1_does_nothing_when_macd_not_falling():
    """hist 上升 → 不触发。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_rising()},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
    assert "X" not in s._sell_state


def test_stage1_first_trigger_sells_15pct_and_records_pref():
    """首次触发:1000 股 → 卖 150 股(15%);记录 P_ref = 当周 (high+low)/2。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_falling()},
        valuation={"X": {"peTTM": 25.0}},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150)]
    assert ctx.removed_targets == []
    state = s._sell_state["X"]
    assert state["stage"] == 1
    assert state["initial_shares"] == 1000
    # 当周(末根) bar:close=159, high=159.5, low=158.5 → P_ref = 159.0
    assert state["p_ref"] == 159.0


def test_stage1_weekly_cadence_same_week_no_double():
    """同一周内多次调用 on_sell,Stage 1 只触发一次。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_falling()},
        valuation={"X": {"peTTM": 25.0}},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    s.on_sell(ctx)
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150)]


def test_stage1_disabled_by_param():
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_falling()},
    )
    s = MaTangleValueStrategy(param_overrides={"macd_sell_enabled": False})
    s.on_sell(ctx)
    assert ctx.orders == []


def test_stage1_no_position_skipped():
    ctx = _SellCtx(
        positions={"X": 0},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_falling()},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []


def test_stage1_no_weekly_data_skipped():
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []


# ===== 2b. Stage 1 PE 闸门(2026-05-24 新增)=====


def test_stage1_blocked_when_pe_below_min():
    """MACD 触发但 PE=15 ≤ 20 → 不卖(估值不够高)。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_falling()},
        valuation={"X": {"peTTM": 15.0}},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
    assert "X" not in s._sell_state


def test_stage1_blocked_when_pe_missing():
    """MACD 触发但 valuation 缺失/无 peTTM → 保守不卖。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_falling()},
        # 不传 valuation
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
    assert "X" not in s._sell_state


def test_stage1_pe_min_overridable():
    """参数覆盖 macd_sell_pe_min=10 → PE=15 也能触发。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_falling()},
        valuation={"X": {"peTTM": 15.0}},
    )
    s = MaTangleValueStrategy(param_overrides={"macd_sell_pe_min": 10.0})
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150)]
    assert s._sell_state["X"]["stage"] == 1


# ===== 3. Stage 2:Stage 1 之后,daily close > P_ref * 1.05 → 卖 20% =====


def test_stage2_triggers_when_close_breaks_pref_by_5pct():
    """Stage 1 已卖 150 股,P_ref=159;后续日 close=167 (>159*1.05=166.95) → 卖 200 股。"""
    s = MaTangleValueStrategy()
    # 手动注入 stage 1 已完成的状态
    s._sell_state["X"] = {
        "stage": 1,
        "initial_shares": 1000,
        "p_ref": 159.0,
        "stage1_week": "2024-W49",
    }
    ctx = _SellCtx(
        positions={"X": 850},  # 1000 - 150
        current_date="2025-01-15",
        price={"X": {"daily": {"close": 167.0, "high": 168.0, "low": 166.0}}},
        history={"X__weekly": _bars_hist_falling()},
    )
    ctx.orders = []
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
        "stage1_week": "2024-W49",
    }
    ctx = _SellCtx(
        positions={"X": 850},
        current_date="2025-01-15",
        price={"X": {"daily": {"close": 166.5, "high": 167.0, "low": 166.0}}},
        history={"X__weekly": _bars_hist_falling()},
    )
    ctx.orders = []
    s.on_sell(ctx)
    assert ctx.orders == []
    assert s._sell_state["X"]["stage"] == 1


def test_stage2_only_triggers_once():
    """Stage 2 触发后,再有 close 突破也不再卖。"""
    s = MaTangleValueStrategy()
    s._sell_state["X"] = {
        "stage": 1,
        "initial_shares": 1000,
        "p_ref": 159.0,
        "stage1_week": "2024-W49",
    }
    ctx = _SellCtx(
        positions={"X": 850},
        current_date="2025-01-15",
        price={"X": {"daily": {"close": 170.0}}},
        history={"X__weekly": _bars_hist_falling()},
    )
    ctx.orders = []
    s.on_sell(ctx)
    assert len(ctx.orders) == 1

    # 第 2 天再次调用,价格更高 → 不应再卖
    ctx.current_date = "2025-01-16"
    s.on_sell(ctx)
    assert len(ctx.orders) == 1


def test_full_lifecycle_stage1_then_stage2():
    """Stage 1 → 多日观察 → Stage 2 触发,最终 35% 卖出。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _bars_hist_falling()},
        # daily close 一开始低于 P_ref*1.05,后来突破
        price={"X": {"daily": {"close": 159.5}}},
        valuation={"X": {"peTTM": 25.0}},
    )
    s = MaTangleValueStrategy()

    # Stage 1 触发(week 49):卖 150
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150)]
    p_ref = s._sell_state["X"]["p_ref"]
    assert p_ref == 159.0

    # 模拟持仓减少
    ctx._positions["X"].shares = 850

    # 第 2 天 close=160(< 166.95)→ 不卖
    ctx.current_date = "2024-12-07"
    ctx._price = {"X": {"daily": {"close": 160.0}}}
    s.on_sell(ctx)
    assert len(ctx.orders) == 1

    # 第 N 天 close=170(> 166.95)→ Stage 2 卖 200
    ctx.current_date = "2025-02-10"
    ctx._price = {"X": {"daily": {"close": 170.0}}}
    s.on_sell(ctx)
    assert ctx.orders == [("X", -150), ("X", -200)]
    assert s._sell_state["X"]["stage"] == 2
    assert ctx.removed_targets == ["X"]
    # 总共卖 35%,剩 65%
    total_sold = -sum(o[1] for o in ctx.orders)
    assert total_sold == 350
