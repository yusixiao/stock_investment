import pytest
from services.backtest.base import BuyStrategy, SellStrategy


class TestBuyStrategy:
    def test_strategy_type(self):
        class MyBuy(BuyStrategy):
            name = "test_buy"
            params = {"threshold": {"default": 0.5}}

        s = MyBuy()
        assert s.strategy_type == "buy"

    def test_on_bar_raises(self):
        class MyBuy(BuyStrategy):
            name = "test_buy"

        s = MyBuy()
        with pytest.raises(NotImplementedError):
            s.on_bar(None)

    def test_params_with_overrides(self):
        class MyBuy(BuyStrategy):
            name = "test_buy"
            params = {"threshold": {"default": 0.5}, "period": {"default": 20}}

        s = MyBuy(param_overrides={"threshold": 0.8})
        assert s.p.threshold == 0.8
        assert s.p.period == 20


class TestSellStrategy:
    def test_strategy_type(self):
        class MySell(SellStrategy):
            name = "test_sell"
            params = {"stop_loss": {"default": 0.1}}

        s = MySell()
        assert s.strategy_type == "sell"

    def test_on_bar_raises(self):
        class MySell(SellStrategy):
            name = "test_sell"

        s = MySell()
        with pytest.raises(NotImplementedError):
            s.on_bar(None)

    def test_params_with_overrides(self):
        class MySell(SellStrategy):
            name = "test_sell"
            params = {"stop_loss": {"default": 0.1}, "take_profit": {"default": 0.3}}

        s = MySell(param_overrides={"stop_loss": 0.05})
        assert s.p.stop_loss == 0.05
        assert s.p.take_profit == 0.3
