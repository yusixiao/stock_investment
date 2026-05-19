"""Strategy 新基类单测(Phase 1)。
旧的 ScreenerStrategy/TraderStrategy/BuyStrategy/SellStrategy 在本 Phase 仍并存,
本测试仅覆盖新增 Strategy 类。"""

import pytest
from strategies.base import Strategy


def test_default_screen_returns_input_symbols():
    s = Strategy()
    assert s.screen(ctx=None, symbols=["A", "B"]) == ["A", "B"]


def test_default_on_buy_and_on_sell_are_noop():
    s = Strategy()
    s.on_buy(ctx=None)
    s.on_sell(ctx=None)


def test_default_frequency_is_daily_and_locked():
    assert Strategy.frequency == "daily"
    assert Strategy.frequency_overridable is False


def test_settings_merges_class_settings_with_defaults():
    class MyStrat(Strategy):
        settings = {"commission_rate": 0.001}

    s = MyStrat()
    assert s.settings["initial_capital"] == 1_000_000
    assert s.settings["commission_rate"] == 0.001
    assert s.settings["slippage"] == 0.002


def test_param_overrides_via_p_accessor():
    class MyStrat(Strategy):
        params = {"min_x": {"default": 5, "type": "int"}}

    s = MyStrat(param_overrides={"min_x": 10})
    assert s.p.min_x == 10


def test_subclass_can_override_screen():
    class MyStrat(Strategy):
        def screen(self, ctx, symbols):
            return [s for s in symbols if s.startswith("0")]

    s = MyStrat()
    assert s.screen(None, ["000001", "600519"]) == ["000001"]
