import pytest
from services.backtest.base import (
    BaseStrategy,
    ScreenerStrategy,
    TraderStrategy,
    ParamAccessor,
)


class TestParamAccessor:
    def test_access_default_values(self):
        params = {"fast": {"default": 5}, "slow": {"default": 20}}
        p = ParamAccessor(params)
        assert p.fast == 5
        assert p.slow == 20

    def test_override_values(self):
        params = {"fast": {"default": 5}, "slow": {"default": 20}}
        p = ParamAccessor(params, overrides={"fast": 10})
        assert p.fast == 10
        assert p.slow == 20

    def test_missing_param_raises(self):
        p = ParamAccessor({"fast": {"default": 5}})
        with pytest.raises(AttributeError):
            _ = p.missing


class TestBaseStrategy:
    def test_has_required_attrs(self):
        class MyStrategy(BaseStrategy):
            name = "test"
            description = "desc"
            params = {"x": {"default": 1}}

        s = MyStrategy()
        assert s.name == "test"
        assert s.description == "desc"
        assert s.p.x == 1

    def test_with_overrides(self):
        class MyStrategy(BaseStrategy):
            name = "test"
            description = "desc"
            params = {"x": {"default": 1}}

        s = MyStrategy(param_overrides={"x": 99})
        assert s.p.x == 99

    def test_strategy_type(self):
        class MyStrategy(BaseStrategy):
            name = "test"
            description = ""
            params = {}

        s = MyStrategy()
        assert s.strategy_type == "base"


class TestScreenerStrategy:
    def test_strategy_type(self):
        class MyScreener(ScreenerStrategy):
            name = "test"
            description = ""
            params = {}
            def screen(self, ctx, symbols):
                return symbols

        s = MyScreener()
        assert s.strategy_type == "screener"

    def test_screen_must_be_implemented(self):
        class BadScreener(ScreenerStrategy):
            name = "test"
            description = ""
            params = {}

        s = BadScreener()
        with pytest.raises(NotImplementedError):
            s.screen(None, [])


class TestTraderStrategy:
    def test_strategy_type(self):
        class MyTrader(TraderStrategy):
            name = "test"
            description = ""
            params = {}
            settings = {"initial_capital": 1_000_000}
            def on_bar(self, ctx):
                pass

        s = MyTrader()
        assert s.strategy_type == "trader"
        assert s.settings["initial_capital"] == 1_000_000

    def test_on_bar_must_be_implemented(self):
        class BadTrader(TraderStrategy):
            name = "test"
            description = ""
            params = {}
            settings = {}

        s = BadTrader()
        with pytest.raises(NotImplementedError):
            s.on_bar(None)

    def test_default_settings(self):
        class MyTrader(TraderStrategy):
            name = "test"
            description = ""
            params = {}
            def on_bar(self, ctx):
                pass

        s = MyTrader()
        assert s.settings["initial_capital"] == 1_000_000
        assert s.settings["commission_rate"] == 0.0003
        assert s.settings["slippage"] == 0.002
