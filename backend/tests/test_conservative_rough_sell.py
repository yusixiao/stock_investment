"""ConservativeRoughStrategy.on_sell 选项 3:screen pool 动态白名单卖出。

语义:持仓不在最新一次 screen 输出的 pool 里 → 全部清仓 + 从累计池移除。
"""

from __future__ import annotations

from tests.utils_test_helpers import MockContext

from strategies.examples.conservative_rough_strategy import ConservativeRoughStrategy


def _strat() -> ConservativeRoughStrategy:
    """避免跑完整 screen,直接构造策略并手动注入 _last_screen_pool。"""
    return ConservativeRoughStrategy()


def test_on_sell_no_screen_run_yet_is_noop():
    """screen() 未跑过(_last_screen_pool 不存在)→ 不卖任何东西。"""
    s = _strat()
    ctx = MockContext()
    ctx.set_positions({"A": 1000})
    s.on_sell(ctx)
    assert ctx.orders == []
    assert ctx.removed_targets == []


def test_on_sell_position_in_pool_is_kept():
    """持仓在最新 screen pool 中 → 不卖。"""
    s = _strat()
    s._last_screen_pool = {"A", "B"}
    ctx = MockContext()
    ctx.set_positions({"A": 1000, "B": 500})
    s.on_sell(ctx)
    assert ctx.orders == []
    assert ctx.removed_targets == []


def test_on_sell_position_dropped_out_is_sold():
    """持仓 A 在 pool,持仓 B 不在 → B 被全数清仓,A 保留。"""
    s = _strat()
    s._last_screen_pool = {"A"}
    ctx = MockContext()
    ctx.set_positions({"A": 1000, "B": 500})
    s.on_sell(ctx)
    # 只卖 B,负数表示卖出
    assert ctx.orders == [("B", -500)]
    assert ctx.removed_targets == ["B"]


def test_on_sell_multiple_dropouts_all_sold():
    """多个持仓掉出 pool → 全部清仓。"""
    s = _strat()
    s._last_screen_pool = set()  # 全空 pool
    ctx = MockContext()
    ctx.set_positions({"A": 100, "B": 200, "C": 300})
    s.on_sell(ctx)
    sold = sorted(ctx.orders)
    assert sold == [("A", -100), ("B", -200), ("C", -300)]
    assert sorted(ctx.removed_targets) == ["A", "B", "C"]


def test_on_sell_zero_share_position_skipped():
    """0 股位置不应触发卖单(防御性,真实 portfolio 已自动清理 0 股)。"""
    s = _strat()
    s._last_screen_pool = set()
    ctx = MockContext()
    ctx.set_positions({"A": 0})
    s.on_sell(ctx)
    assert ctx.orders == []


def test_screen_populates_last_screen_pool():
    """screen() 跑完后,_last_screen_pool 应记录 pool 内容供下一根 bar 的 on_sell 使用。"""
    s = _strat()
    ctx = MockContext()
    # 空 symbols → screen 输出空 pool,但 _last_screen_pool 必须被设置(set 类型)
    result = s.screen(ctx, [])
    assert result == []
    assert hasattr(s, "_last_screen_pool")
    assert s._last_screen_pool == set()
