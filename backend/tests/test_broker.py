import pytest
from services.backtest.broker import Broker, Order
from services.backtest.portfolio import Portfolio


class TestPortfolio:
    def test_initial_state(self):
        p = Portfolio(initial_capital=1_000_000)
        assert p.cash == 1_000_000
        assert p.get_total_value({}) == 1_000_000
        assert p.get_positions() == []

    def test_buy_updates_position(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=100, price=1800.0, commission=54.0, date="2024-01-15")
        pos = p.get_position("600519.SH")
        assert pos is not None
        assert pos["shares"] == 100
        assert pos["cost"] == 1800.0
        assert p.cash == 1_000_000 - 100 * 1800.0 - 54.0

    def test_sell_updates_position(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=100, price=1800.0, commission=54.0, date="2024-01-15")
        p.sell("600519.SH", shares=100, price=1900.0, commission=57.0, tax=190.0)
        pos = p.get_position("600519.SH")
        assert pos is None
        assert p.get_positions() == []

    def test_sell_partial(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=200, price=100.0, commission=5.0, date="2024-01-15")
        p.sell("600519.SH", shares=100, price=110.0, commission=5.0, tax=11.0)
        pos = p.get_position("600519.SH")
        assert pos["shares"] == 100

    def test_total_value_with_positions(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=100, price=100.0, commission=5.0, date="2024-01-15")
        prices = {"600519.SH": 110.0}
        total = p.get_total_value(prices)
        expected = p.cash + 100 * 110.0
        assert total == expected

    def test_snapshot(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=100, price=100.0, commission=5.0, date="2024-01-15")
        snap = p.snapshot("2024-01-15", {"600519.SH": 105.0})
        assert snap["date"] == "2024-01-15"
        assert snap["cash"] == p.cash
        assert snap["market_value"] == 100 * 105.0
        assert snap["total_value"] == p.cash + 100 * 105.0


class TestBroker:
    def _make_broker(self, capital=1_000_000, commission_rate=0.0003, slippage=0.002):
        return Broker(
            initial_capital=capital,
            commission_rate=commission_rate,
            slippage=slippage,
        )

    def test_submit_buy_order(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        assert len(b.pending_orders) == 1
        assert b.pending_orders[0].direction == "buy"

    def test_fill_buy_order(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        prev_close = 95.0
        trades = b.fill_orders(
            "2024-01-16", {"600519.SH": bar}, {"600519.SH": prev_close}
        )
        assert len(trades) == 1
        assert trades[0]["direction"] == "buy"
        assert trades[0]["shares"] == 100

    def test_commission_minimum_5(self):
        b = self._make_broker(commission_rate=0.0003)
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 10.0, "close": 10.0, "high": 10.0, "low": 10.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 9.5})
        assert trades[0]["commission"] == 5.0

    def test_sell_includes_tax(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        bar2 = {"open": 110.0, "close": 110.0, "high": 115.0, "low": 105.0}
        trades = b.fill_orders("2024-01-17", {"600519.SH": bar2}, {"600519.SH": 100.0})
        sell_trade = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trade) == 1
        assert sell_trade[0]["tax"] > 0

    def test_t_plus_1_rejects_same_day_sell(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        bar2 = {"open": 105.0, "close": 105.0, "high": 110.0, "low": 100.0}
        trades = b.fill_orders("2024-01-15", {"600519.SH": bar2}, {"600519.SH": 100.0})
        sell_trades = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trades) == 0

    def test_t_plus_1_allows_next_day_sell(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        bar2 = {"open": 105.0, "close": 105.0, "high": 110.0, "low": 100.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar2}, {"600519.SH": 100.0})
        sell_trades = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trades) == 1

    def test_limit_up_rejects_buy(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        prev_close = 100.0
        limit_up = round(prev_close * 1.1, 2)
        bar = {"open": limit_up, "close": limit_up, "high": limit_up, "low": limit_up}
        trades = b.fill_orders(
            "2024-01-16", {"600519.SH": bar}, {"600519.SH": prev_close}
        )
        assert len(trades) == 0

    def test_limit_down_rejects_sell(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        prev_close = 100.0
        limit_down = round(prev_close * 0.9, 2)
        bar2 = {
            "open": limit_down,
            "close": limit_down,
            "high": limit_down,
            "low": limit_down,
        }
        trades = b.fill_orders(
            "2024-01-16", {"600519.SH": bar2}, {"600519.SH": prev_close}
        )
        sell_trades = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trades) == 0

    def test_volume_zero_rejects_buy(self):
        """停牌日 volume=0,broker 必须拒单(防止 BaoStock 填充 bar 误成交)。"""
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        # 模拟停牌:OHLC 全等于 prev_close,volume=0
        bar = {"open": 100.0, "close": 100.0, "high": 100.0, "low": 100.0, "volume": 0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 100.0})
        assert len(trades) == 0

    def test_volume_zero_rejects_sell(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {
            "open": 100.0,
            "close": 100.0,
            "high": 110.0,
            "low": 90.0,
            "volume": 1000,
        }
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        bar2 = {"open": 100.0, "close": 100.0, "high": 100.0, "low": 100.0, "volume": 0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar2}, {"600519.SH": 100.0})
        sell_trades = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trades) == 0

    def test_missing_volume_field_allows_fill(self):
        """老调用方未提供 volume 字段时保持向后兼容(不拒单)。"""
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 95.0})
        assert len(trades) == 1

    def test_buy_rounds_to_100_shares(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=150, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 95.0})
        assert trades[0]["shares"] == 100

    def test_slippage_applied(self):
        b = self._make_broker(slippage=0.01)
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 95.0})
        mid_price = (100.0 + 100.0) / 2
        expected_price = mid_price * (1 + 0.01)
        assert abs(trades[0]["price"] - expected_price) < 0.01

    def test_insufficient_funds_rejects(self):
        """现金连一手都买不起时,整单拒绝。"""
        b = self._make_broker(capital=1000)
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 95.0})
        assert len(trades) == 0

    def test_insufficient_funds_partial_fill(self):
        """资金不足以买满目标手数时,按可用现金买最大整百手【部分成交】,而非整单拒绝。

        避免"差一点点就整单丢弃、导致近一整个仓位的现金空转"(等权满仓策略在
        每次调仓最后一只上系统性发生)。排序靠前的已按目标买满,只有排序最后
        (现金不够的)那只被缩减,策略排序优先级不受影响。
        """
        b = self._make_broker(capital=50_000)
        b.submit_order("600519.SH", shares=1000, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 95.0})
        # fill_price = 100*(1+0.002)=100.2;50000/(100.2*1.0003)=498.8 → 整百手=400
        assert len(trades) == 1
        assert trades[0]["shares"] == 400
        assert trades[0]["shares"] < 1000  # 确为部分成交,非整单
        # 成交总成本不得超过初始可用现金,且现金非负
        cost = trades[0]["shares"] * trades[0]["price"] + trades[0]["commission"]
        assert cost <= 50_000
        assert b.portfolio.cash >= 0
        # 再多买一手(500)必然超出预算,验证 400 是可买上界
        assert 500 * trades[0]["price"] + 5.0 > 50_000
