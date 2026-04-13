import math
import pandas as pd
from services.indicator import calc_ma, calc_macd, calc_kdj, calc_boll
from services.stock_data import aggregate_kline
from services.backtest.portfolio import Portfolio


class ScreenerContext:
    def __init__(self, stock_data: dict[str, pd.DataFrame], current_idx: int):
        self._stock_data = stock_data
        self._current_idx = current_idx
        self._indicator_cache: dict[str, pd.DataFrame] = {}
        ref_sym = next(iter(stock_data))
        self._current_date = stock_data[ref_sym].iloc[current_idx]["date"]

    @property
    def current_date(self) -> str:
        return self._current_date

    def get_price(self, symbol: str) -> dict | None:
        if symbol not in self._stock_data:
            return None
        df = self._stock_data[symbol]
        if self._current_idx >= len(df):
            return None
        row = df.iloc[self._current_idx]
        return row.to_dict()

    def get_history(self, symbol: str, n: int) -> list[dict]:
        if symbol not in self._stock_data:
            return []
        df = self._stock_data[symbol]
        start = max(0, self._current_idx - n + 1)
        end = self._current_idx + 1
        return df.iloc[start:end].to_dict(orient="records")

    def indicator(self, symbol: str, ind_type: str, *args, period: str = "daily") -> float | None:
        if symbol not in self._stock_data:
            return None
        df = self._stock_data[symbol]
        data_up_to = df.iloc[: self._current_idx + 1]
        if len(data_up_to) < 2:
            return None

        if period in ("weekly", "monthly"):
            cache_key = f"{symbol}_{period}_agg"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = aggregate_kline(data_up_to, period=period)
            data_up_to = self._indicator_cache[cache_key]
            if len(data_up_to) < 2:
                return None

        if ind_type == "ma":
            window = args[0] if args else 5
            cache_key = f"{symbol}_{period}_ma_{window}"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = calc_ma(data_up_to, windows=[window])
            result_df = self._indicator_cache[cache_key]
            col = f"ma{window}"
            if col not in result_df.columns:
                return None
            sorted_df = result_df.sort_values("date")
            val = sorted_df[col].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "macd":
            field_name = args[0] if args else "dif"
            cache_key = f"{symbol}_{period}_macd"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = calc_macd(data_up_to)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            sorted_df = result_df.sort_values("date")
            val = sorted_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "kdj":
            field_name = args[0] if args else "k"
            cache_key = f"{symbol}_{period}_kdj"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = calc_kdj(data_up_to)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            sorted_df = result_df.sort_values("date")
            val = sorted_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "boll":
            field_name = args[0] if args else "boll_mid"
            cache_key = f"{symbol}_{period}_boll"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = calc_boll(data_up_to)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            sorted_df = result_df.sort_values("date")
            val = sorted_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        return None


class TraderContext(ScreenerContext):
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        current_idx: int,
        portfolio: Portfolio,
        broker_submit,
        selected_symbols: list[str],
        days_since_rebalance: int = 0,
    ):
        super().__init__(stock_data, current_idx)
        self._portfolio = portfolio
        self._broker_submit = broker_submit
        self.selected_symbols = selected_symbols
        self.days_since_rebalance = days_since_rebalance

    def reset_rebalance_counter(self):
        self.days_since_rebalance = 0

    def get_position(self, symbol: str) -> dict | None:
        return self._portfolio.get_position(symbol)

    def get_positions(self) -> list[str]:
        return self._portfolio.get_positions()

    def get_portfolio(self) -> dict:
        prices = {}
        for sym in self._portfolio.get_positions():
            p = self.get_price(sym)
            if p:
                prices[sym] = p["close"]
        return {
            "cash": self._portfolio.cash,
            "total_value": self._portfolio.get_total_value(prices),
            "market_value": self._portfolio.get_market_value(prices),
        }

    def order_target_percent(self, symbol: str, percent: float):
        prices = {}
        for sym in self._portfolio.get_positions():
            p = self.get_price(sym)
            if p:
                prices[sym] = p["close"]
        total_value = self._portfolio.get_total_value(prices)
        target_value = total_value * percent
        current_price = self.get_price(symbol)
        if current_price is None:
            return
        pos = self._portfolio.get_position(symbol)
        current_value = (pos["shares"] * current_price["close"]) if pos else 0.0
        diff_value = target_value - current_value
        if abs(diff_value) < current_price["close"]:
            return
        shares = int(abs(diff_value) / current_price["close"])
        if diff_value > 0:
            self._broker_submit(symbol, shares, "buy")
        else:
            self._broker_submit(symbol, shares, "sell")

    def order_shares(self, symbol: str, shares: int):
        if shares > 0:
            self._broker_submit(symbol, shares, "buy")
        elif shares < 0:
            self._broker_submit(symbol, -shares, "sell")

    def order_value(self, symbol: str, value: float):
        current_price = self.get_price(symbol)
        if current_price is None:
            return
        shares = int(abs(value) / current_price["close"])
        if value > 0:
            self._broker_submit(symbol, shares, "buy")
        elif value < 0:
            self._broker_submit(symbol, shares, "sell")
