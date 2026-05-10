import pandas as pd
import pytest
from services.backtest.buy_sell_engine import BuySellEngine
from services.backtest.base import ScreenerStrategy, BuyStrategy, SellStrategy


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]
    data = {}
    for sym in ["000001", "000002", "000003"]:
        base = 10.0 if sym == "000001" else (20.0 if sym == "000002" else 30.0)
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


class SimpleScreener(ScreenerStrategy):
    name = "simple"
    frequency = "daily"

    def screen(self, ctx, symbols):
        return [symbols[0]]


class SimpleBuyer(BuyStrategy):
    name = "simple_buyer"

    def on_bar(self, ctx):
        portfolio = ctx.get_portfolio()
        cash = portfolio["cash"]
        for sym in ctx.selected_symbols:
            price = ctx.get_price(sym)
            if price and cash > 10000:
                shares = int(cash * 0.3 / price["close"]) // 100 * 100
                if shares > 0:
                    ctx.order_shares(sym, shares)
                    break


class SimpleSeller(SellStrategy):
    name = "simple_seller"

    def on_bar(self, ctx):
        for sym in ctx.get_positions():
            pos = ctx.get_position(sym)
            if pos and pos["shares"] > 0:
                price = ctx.get_price(sym)
                if price and price["close"] > pos["avg_cost"] * 1.05:
                    ctx.order_shares(sym, -pos["shares"])


def test_buy_sell_engine_basic():
    stock_data = _make_stock_data()
    screener = SimpleScreener()
    buyer = SimpleBuyer()
    seller = SimpleSeller()

    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=[screener],
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
    )
    result = engine.run()

    assert "metrics" in result
    assert "equity_curve" in result
    assert "trades" in result
    assert len(result["equity_curve"]) == 21
    assert "total_return" in result["metrics"]


def test_buy_sell_engine_no_screener():
    stock_data = _make_stock_data()
    buyer = SimpleBuyer()
    seller = SimpleSeller()

    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=None,
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
    )
    result = engine.run()

    assert "metrics" in result
    assert "equity_curve" in result
    assert "trades" in result
    assert len(result["equity_curve"]) == 21
    assert result["metrics"]["trade_count"] > 0
