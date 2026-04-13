from dataclasses import dataclass, field
from services.backtest.portfolio import Portfolio


@dataclass
class Order:
    symbol: str
    shares: int
    direction: str
    status: str = "pending"


class Broker:
    def __init__(
        self,
        initial_capital: float = 1_000_000,
        commission_rate: float = 0.0003,
        slippage: float = 0.002,
    ):
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.portfolio = Portfolio(initial_capital)
        self.pending_orders: list[Order] = []
        self.all_trades: list[dict] = []

    def submit_order(self, symbol: str, shares: int, direction: str):
        self.pending_orders.append(Order(symbol=symbol, shares=shares, direction=direction))

    def fill_orders(
        self,
        date: str,
        bars: dict[str, dict],
        prev_closes: dict[str, float],
    ) -> list[dict]:
        trades = []
        remaining = []
        for order in self.pending_orders:
            bar = bars.get(order.symbol)
            if bar is None:
                remaining.append(order)
                continue
            prev_close = prev_closes.get(order.symbol)
            trade = self._try_fill(order, bar, prev_close, date)
            if trade is not None:
                trades.append(trade)
        self.pending_orders = remaining
        self.all_trades.extend(trades)
        return trades

    def _try_fill(self, order: Order, bar: dict, prev_close: float | None, date: str) -> dict | None:
        mid_price = (bar["open"] + bar["close"]) / 2

        if prev_close is not None:
            limit_up = round(prev_close * 1.1, 2)
            limit_down = round(prev_close * 0.9, 2)
            is_limit_up = (bar["low"] == bar["high"] == limit_up)
            is_limit_down = (bar["low"] == bar["high"] == limit_down)
            if order.direction == "buy" and is_limit_up:
                return None
            if order.direction == "sell" and is_limit_down:
                return None

        if order.direction == "buy":
            fill_price = mid_price * (1 + self.slippage)
            shares = (order.shares // 100) * 100
            if shares <= 0:
                return None
            commission = max(shares * fill_price * self.commission_rate, 5.0)
            total_cost = shares * fill_price + commission
            if total_cost > self.portfolio.cash:
                return None
            self.portfolio.buy(order.symbol, shares, fill_price, commission, date)
            return {
                "date": date,
                "symbol": order.symbol,
                "direction": "buy",
                "price": fill_price,
                "shares": shares,
                "commission": commission,
                "tax": 0.0,
                "amount": shares * fill_price,
            }

        elif order.direction == "sell":
            pos = self.portfolio.get_position(order.symbol)
            if pos is None:
                return None
            if pos["buy_date"] >= date:
                return None
            sell_shares = min(order.shares, pos["shares"])
            if sell_shares <= 0:
                return None
            fill_price = mid_price * (1 - self.slippage)
            commission = max(sell_shares * fill_price * self.commission_rate, 5.0)
            tax = sell_shares * fill_price * 0.001
            self.portfolio.sell(order.symbol, sell_shares, fill_price, commission, tax)
            return {
                "date": date,
                "symbol": order.symbol,
                "direction": "sell",
                "price": fill_price,
                "shares": sell_shares,
                "commission": commission,
                "tax": tax,
                "amount": sell_shares * fill_price,
            }

        return None
