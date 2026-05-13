import pandas as pd
import pytest
from services.backtest.buy_sell_engine import BuySellEngine
from services.backtest.base import BuyStrategy, SellStrategy


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]
    data = {}
    for sym in ["000001", "000002"]:
        base = 10.0 if sym == "000001" else 20.0
        rows = []
        for i, d in enumerate(dates):
            price = base + i * 0.1
            rows.append({
                "date": d,
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price + 0.05,
                "volume": 1000000.0,
                "amount": 10000000.0,
            })
        data[sym] = pd.DataFrame(rows)
    return data


class AlwaysBuyer(BuyStrategy):
    name = "always_buyer"

    def on_bar(self, ctx):
        portfolio = ctx.get_portfolio()
        cash = portfolio["cash"]
        for sym in ctx.selected_symbols:
            pos = ctx.get_position(sym)
            if pos and pos["shares"] > 0:
                continue
            price = ctx.get_price(sym)
            if price and cash > 10000:
                shares = int(cash * 0.3 / price["close"]) // 100 * 100
                if shares > 0:
                    ctx.order_shares(sym, shares)
                    cash -= shares * price["close"]


class NeverSeller(SellStrategy):
    name = "never_seller"

    def on_bar(self, ctx):
        pass


class SellOnDateX(SellStrategy):
    name = "sell_on_date"

    def __init__(self, target_date: str):
        super().__init__()
        self._target_date = target_date

    def on_bar(self, ctx):
        if ctx._current_date == self._target_date:
            for sym in ctx.get_positions():
                pos = ctx.get_position(sym)
                if pos and pos["shares"] > 0:
                    ctx.order_shares(sym, -pos["shares"])


def test_signal_table_only_buys_on_signal_dates():
    stock_data = _make_stock_data()
    signal_table = {
        "2024-01-05": ["000001"],
        "2024-01-10": ["000002"],
    }

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=AlwaysBuyer(),
        seller=NeverSeller(),
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    result = engine.run()

    trades = result["trades"]
    buy_trades = [t for t in trades if t["direction"] == "buy"]

    assert len(buy_trades) == 2

    t1 = [t for t in buy_trades if t["symbol"] == "000001"]
    assert len(t1) == 1
    assert t1[0]["date"] == "2024-01-06"

    t2 = [t for t in buy_trades if t["symbol"] == "000002"]
    assert len(t2) == 1
    assert t2[0]["date"] == "2024-01-11"

    non_signal_dates = set(f"2024-01-{d:02d}" for d in range(2, 23)) - {"2024-01-05", "2024-01-10"}
    for t in buy_trades:
        order_date = f"2024-01-{int(t['date'][-2:]) - 1:02d}"
        assert order_date in signal_table


def test_signal_table_seller_runs_every_bar():
    stock_data = _make_stock_data()
    signal_table = {
        "2024-01-03": ["000001"],
    }

    sell_date = "2024-01-08"
    seller = SellOnDateX(target_date=sell_date)

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=AlwaysBuyer(),
        seller=seller,
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    result = engine.run()

    trades = result["trades"]
    buy_trades = [t for t in trades if t["direction"] == "buy"]
    sell_trades = [t for t in trades if t["direction"] == "sell"]

    # 第一次买入：信号日2024-01-03 → T+1成交2024-01-04
    assert buy_trades[0]["symbol"] == "000001"
    assert buy_trades[0]["date"] == "2024-01-04"

    assert len(sell_trades) == 1
    assert sell_trades[0]["symbol"] == "000001"
    assert sell_trades[0]["date"] == "2024-01-09"

    # Buyer 每日执行，卖出后因 target_symbols 仍有000001，会再次买入
    assert len(buy_trades) >= 2

    assert sell_date not in signal_table


def test_signal_table_empty_means_no_buy():
    stock_data = _make_stock_data()
    signal_table = {}

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=AlwaysBuyer(),
        seller=NeverSeller(),
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    result = engine.run()

    trades = result["trades"]
    assert len(trades) == 0
