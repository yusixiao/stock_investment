import sqlite3
from datetime import datetime


class PortfolioManager:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_portfolio(self, name: str, initial_capital: float, source: str = "manual") -> dict:
        now = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO portfolios (name, initial_capital, source, created_at) VALUES (?, ?, ?, ?)",
            (name, initial_capital, source, now),
        )
        self._conn.commit()
        return {
            "id": cur.lastrowid,
            "name": name,
            "initial_capital": initial_capital,
            "source": source,
            "created_at": now,
        }

    def delete_portfolio(self, portfolio_id: int):
        self._conn.execute("DELETE FROM portfolios WHERE id=?", (portfolio_id,))
        self._conn.commit()

    def list_portfolios(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM portfolios ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_portfolio(self, portfolio_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM portfolios WHERE id=?", (portfolio_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def add_trade(
        self,
        portfolio_id: int,
        symbol: str,
        direction: str,
        price: float,
        shares: int,
        trade_date: str,
        commission: float | None = None,
    ) -> dict:
        amount = price * shares
        if commission is None:
            commission = max(amount * 0.0003, 5.0)
        tax = amount * 0.001 if direction == "sell" else 0.0
        now = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO trades (portfolio_id, symbol, direction, price, shares, commission, tax, trade_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (portfolio_id, symbol, direction, price, shares, commission, tax, trade_date, now),
        )
        self._conn.commit()
        return {
            "id": cur.lastrowid,
            "portfolio_id": portfolio_id,
            "symbol": symbol,
            "direction": direction,
            "price": price,
            "shares": shares,
            "commission": commission,
            "tax": tax,
            "trade_date": trade_date,
            "created_at": now,
        }

    def get_trades(self, portfolio_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE portfolio_id=? ORDER BY trade_date, id",
            (portfolio_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def compute_holdings(self, portfolio_id: int) -> dict:
        trades = self.get_trades(portfolio_id)
        holdings: dict[str, dict] = {}
        for t in trades:
            sym = t["symbol"]
            if sym not in holdings:
                holdings[sym] = {"shares": 0, "total_cost": 0.0}
            h = holdings[sym]
            if t["direction"] == "buy":
                old_total = h["total_cost"]
                new_cost = t["price"] * t["shares"]
                h["total_cost"] = old_total + new_cost
                h["shares"] += t["shares"]
            elif t["direction"] == "sell":
                h["shares"] -= t["shares"]
                if h["shares"] > 0:
                    h["total_cost"] = h["total_cost"] * (h["shares"] / (h["shares"] + t["shares"]))
                else:
                    h["total_cost"] = 0.0

        result = {}
        for sym, h in holdings.items():
            if h["shares"] > 0:
                result[sym] = {
                    "shares": h["shares"],
                    "avg_cost": h["total_cost"] / h["shares"],
                }
        return result

    def _compute_cash(self, portfolio_id: int) -> float:
        p = self.get_portfolio(portfolio_id)
        if p is None:
            return 0.0
        cash = p["initial_capital"]
        trades = self.get_trades(portfolio_id)
        for t in trades:
            if t["direction"] == "buy":
                cash -= t["price"] * t["shares"] + t["commission"]
            elif t["direction"] == "sell":
                cash += t["price"] * t["shares"] - t["commission"] - t["tax"]
        return cash

    def compute_summary(self, portfolio_id: int, current_prices: dict[str, float] | None = None) -> dict:
        p = self.get_portfolio(portfolio_id)
        if p is None:
            return {}
        if current_prices is None:
            current_prices = {}
        holdings = self.compute_holdings(portfolio_id)
        cash = self._compute_cash(portfolio_id)
        market_value = sum(
            h["shares"] * current_prices.get(sym, h["avg_cost"])
            for sym, h in holdings.items()
        )
        total_value = cash + market_value
        initial = p["initial_capital"]
        total_return = (total_value - initial) / initial if initial > 0 else 0.0
        return {
            "cash": cash,
            "market_value": market_value,
            "total_value": total_value,
            "total_return": total_return,
        }

    def take_snapshot(self, portfolio_id: int, date: str, current_prices: dict[str, float]):
        summary = self.compute_summary(portfolio_id, current_prices)
        if not summary:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots (portfolio_id, date, total_value, cash, market_value) VALUES (?, ?, ?, ?, ?)",
            (portfolio_id, date, summary["total_value"], summary["cash"], summary["market_value"]),
        )
        self._conn.commit()

    def take_all_snapshots(self, date: str, current_prices: dict[str, float]):
        portfolios = self.list_portfolios()
        for p in portfolios:
            self.take_snapshot(p["id"], date, current_prices)

    def get_snapshots(self, portfolio_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM snapshots WHERE portfolio_id=? ORDER BY date",
            (portfolio_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def import_from_backtest(self, backtest_result: dict, name: str) -> dict:
        equity_curve = backtest_result["equity_curve"]
        last_snap = equity_curve[-1]
        total_value = last_snap["total_value"]
        positions = last_snap.get("positions", {})
        cash = last_snap["cash"]
        trade_date = last_snap["date"]

        p = self.create_portfolio(name, total_value, source="backtest")

        for sym, pos in positions.items():
            self.add_trade(
                p["id"],
                sym,
                "buy",
                pos["cost"],
                pos["shares"],
                trade_date,
                commission=0.0,
            )

        return p
