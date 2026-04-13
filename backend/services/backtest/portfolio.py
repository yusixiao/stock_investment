from dataclasses import dataclass, field


@dataclass
class PositionInfo:
    shares: int = 0
    cost: float = 0.0
    buy_date: str = ""


class Portfolio:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self._positions: dict[str, PositionInfo] = {}

    def buy(self, symbol: str, shares: int, price: float, commission: float, date: str):
        total_cost = shares * price + commission
        self.cash -= total_cost
        if symbol in self._positions:
            pos = self._positions[symbol]
            old_total = pos.shares * pos.cost
            new_total = old_total + shares * price
            pos.shares += shares
            pos.cost = new_total / pos.shares if pos.shares > 0 else 0.0
            pos.buy_date = date
        else:
            self._positions[symbol] = PositionInfo(
                shares=shares, cost=price, buy_date=date
            )

    def sell(self, symbol: str, shares: int, price: float, commission: float, tax: float):
        total_income = shares * price - commission - tax
        self.cash += total_income
        if symbol in self._positions:
            self._positions[symbol].shares -= shares
            if self._positions[symbol].shares <= 0:
                del self._positions[symbol]

    def get_position(self, symbol: str) -> dict | None:
        if symbol not in self._positions:
            return None
        pos = self._positions[symbol]
        return {"shares": pos.shares, "cost": pos.cost, "buy_date": pos.buy_date}

    def get_positions(self) -> list[str]:
        return list(self._positions.keys())

    def get_total_value(self, current_prices: dict[str, float]) -> float:
        market_value = sum(
            pos.shares * current_prices.get(sym, pos.cost)
            for sym, pos in self._positions.items()
        )
        return self.cash + market_value

    def get_market_value(self, current_prices: dict[str, float]) -> float:
        return sum(
            pos.shares * current_prices.get(sym, pos.cost)
            for sym, pos in self._positions.items()
        )

    def snapshot(self, date: str, current_prices: dict[str, float]) -> dict:
        market_value = self.get_market_value(current_prices)
        total_value = self.cash + market_value
        positions = {}
        for sym, pos in self._positions.items():
            positions[sym] = {
                "shares": pos.shares,
                "cost": pos.cost,
                "market_price": current_prices.get(sym, pos.cost),
            }
        return {
            "date": date,
            "total_value": total_value,
            "cash": self.cash,
            "market_value": market_value,
            "positions": positions,
        }
