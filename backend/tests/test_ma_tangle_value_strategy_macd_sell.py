"""MaTangleValueStrategy MACD 分批卖出策略测试(2026-05-24 新增)。

规格:
- 卖出条件:本周 macd_hist > 上周 macd_hist
- 触发频率:每周检查一次(周键变化才执行)
- 每批比例:25%(按首次触发时的持仓份额)
- 共 4 批,最后一批卖出全部剩余,清仓后 remove_target
- 替代原有 PE*PB / MA 跌破退出
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.tests.utils_test_helpers import MockContext
from strategies.examples.ma_tangle_value_strategy import MaTangleValueStrategy


# ===== 共用工具 =====


class _Pos:
    def __init__(self, shares: int):
        self.shares = shares


class _SellCtx(MockContext):
    """扩展 MockContext:支持 positions / remove_target / get_indicator (按需)。"""

    def __init__(self, *, positions: dict[str, int], current_date: str, **kw):
        super().__init__(current_date=current_date, **kw)
        self._positions = {sym: _Pos(n) for sym, n in positions.items()}
        self.removed_targets: list[str] = []

    def get_positions(self) -> dict[str, Any]:
        return self._positions

    def remove_target(self, sym: str) -> None:
        self.removed_targets.append(sym)


def _bars_from_closes(closes: list[float]) -> list[dict]:
    """把 close 列表填成 60 根 weekly bars。"""
    out = []
    for i, c in enumerate(closes):
        out.append(
            {
                "date": f"2024-{(i // 4) + 1:02d}-{((i % 4) * 7) + 1:02d}",
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 1000.0,
                "amount": c * 1000.0,
            }
        )
    return out


def _bars_hist_rising() -> list[dict]:
    """末尾两根 macd_hist 严格上升的周线序列。

    实测:单调递减 closes 在末尾产生递增的负向 hist(回归 0),
    满足"本周 hist > 上周 hist"。
    """
    return _bars_from_closes([200.0 - i * 1.0 for i in range(60)])


def _bars_hist_falling() -> list[dict]:
    """末尾两根 macd_hist 严格下降的周线序列。

    实测:单调递增 closes 在末尾产生递减的正向 hist,不满足卖出条件。
    """
    return _bars_from_closes([100.0 + i * 1.0 for i in range(60)])


def _make_weekly_bars_with_macd_hist(_unused) -> list[dict]:
    """旧名兼容,默认返回 hist 上升序列(用于通用测试)。"""
    return _bars_hist_rising()


# ===== 1. 帮助函数测试 =====


def test_get_macd_hist_series_returns_last_n_values():
    from strategies.utils.kline import get_macd_hist_series

    ctx = MockContext(history={"X__weekly": _make_weekly_bars_with_macd_hist([])})
    series = get_macd_hist_series(ctx, "X", n=2, freq="weekly")
    assert series is not None
    assert len(series) == 2
    assert all(isinstance(v, float) for v in series)


def test_get_macd_hist_series_insufficient_data_returns_none():
    from strategies.utils.kline import get_macd_hist_series

    ctx = MockContext(history={"X__weekly": []})
    series = get_macd_hist_series(ctx, "X", n=2, freq="weekly")
    assert series is None


# ===== 2. 策略元信息 =====


def test_macd_sell_params_present():
    s = MaTangleValueStrategy()
    # 新参数
    assert hasattr(s.p, "macd_sell_enabled")
    assert s.p.macd_sell_enabled is True
    assert hasattr(s.p, "macd_sell_batches")
    assert s.p.macd_sell_batches == 4


def test_old_clearance_sell_params_removed():
    """sell_pe_pb_max / sell_below_ma 已被 MACD 分批卖出替代。"""
    s = MaTangleValueStrategy()
    # 旧参数应当不存在(或至少不再驱动逻辑)
    assert "sell_pe_pb_max" not in s.params
    assert "sell_below_ma" not in s.params


# ===== 3. on_sell 行为 =====


def _ascending_weekly_bars() -> list[dict]:
    """语义:hist 上升 → 触发卖出条件(本周 > 上周)。"""
    return _bars_hist_rising()


def _descending_weekly_bars() -> list[dict]:
    """语义:hist 下降 → 不触发卖出条件。"""
    return _bars_hist_falling()


def test_on_sell_does_nothing_when_macd_not_rising():
    """收盘价单调递减 → hist 不上升,不应下单。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",  # 周五
        history={"X__weekly": _descending_weekly_bars()},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []


def test_on_sell_first_trigger_sells_25pct_of_initial():
    """首次触发卖出:1000 股 → 卖 250 股(25%)。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _ascending_weekly_bars()},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == [("X", -250)]
    # 不应 remove_target(还有 3 批)
    assert ctx.removed_targets == []


def test_on_sell_weekly_cadence_same_week_no_double_sell():
    """同一周内多次调用 on_sell,只应触发一次。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _ascending_weekly_bars()},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    s.on_sell(ctx)
    s.on_sell(ctx)
    assert ctx.orders == [("X", -250)]


def test_on_sell_four_batches_clears_position():
    """连续 4 周条件命中,共卖完 1000 股,最后一批 remove_target。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _ascending_weekly_bars()},
    )
    s = MaTangleValueStrategy()

    # 模拟每周收盘:换日期 → 周键变化 → 触发新一轮
    weeks = [
        "2024-12-06",  # W49
        "2024-12-13",  # W50
        "2024-12-20",  # W51
        "2024-12-27",  # W52
    ]
    for d in weeks:
        ctx.current_date = d
        # 模拟持仓被前一批 sell 减少(回测 broker 会在下一根 bar fill,这里手动同步)
        sold = -sum(o[1] for o in ctx.orders)
        ctx._positions["X"].shares = max(0, 1000 - sold)
        s.on_sell(ctx)

    total_sold = -sum(o[1] for o in ctx.orders)
    assert total_sold == 1000  # 全部卖完
    assert len(ctx.orders) == 4  # 共 4 批
    assert ctx.removed_targets == ["X"]  # 最后一批清仓后 remove


def test_on_sell_pauses_when_condition_breaks():
    """中途某周 MACD 不上升 → 暂停;下周再上升,继续卖剩余批次。"""
    s = MaTangleValueStrategy()

    def _ctx_with(date: str, bars: list[dict], shares: int) -> _SellCtx:
        return _SellCtx(
            positions={"X": shares},
            current_date=date,
            history={"X__weekly": bars},
        )

    asc = _ascending_weekly_bars()
    desc = _descending_weekly_bars()

    # 第 1 周:升 → 卖 250
    ctx = _ctx_with("2024-12-06", asc, 1000)
    s.on_sell(ctx)
    orders_w1 = list(ctx.orders)
    state = dict(s._sell_state)  # 保存策略内部状态

    # 第 2 周:降 → 不卖
    ctx2 = _ctx_with("2024-12-13", desc, 750)
    s._sell_state = state
    s.on_sell(ctx2)
    assert ctx2.orders == []

    # 第 3 周:升 → 卖第二批 250
    ctx3 = _ctx_with("2024-12-20", asc, 750)
    s._sell_state = dict(s._sell_state)  # 用 ctx2 之后的 state
    s.on_sell(ctx3)
    assert ctx3.orders == [("X", -250)]


def test_on_sell_disabled_when_param_off():
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={"X__weekly": _ascending_weekly_bars()},
    )
    s = MaTangleValueStrategy(param_overrides={"macd_sell_enabled": False})
    s.on_sell(ctx)
    assert ctx.orders == []


def test_on_sell_no_position_skipped():
    ctx = _SellCtx(
        positions={"X": 0},
        current_date="2024-12-06",
        history={"X__weekly": _ascending_weekly_bars()},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []


def test_on_sell_no_weekly_data_skipped():
    """没有周线历史 → 跳过,不下单也不报错。"""
    ctx = _SellCtx(
        positions={"X": 1000},
        current_date="2024-12-06",
        history={},
    )
    s = MaTangleValueStrategy()
    s.on_sell(ctx)
    assert ctx.orders == []
