import logging
import math
from dataclasses import dataclass, field

import pandas as pd
from services.indicator import calc_ma, calc_macd, calc_kdj, calc_boll
from services.indicator_store import load_indicators
from services.backtest.portfolio import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class MarketData:
    """行情数据容器，封装各周期和维度的数据字典，减少参数传递。"""

    daily: dict[str, pd.DataFrame] = field(default_factory=dict)
    weekly: dict[str, pd.DataFrame] = field(default_factory=dict)
    monthly: dict[str, pd.DataFrame] = field(default_factory=dict)
    valuation: dict[str, pd.DataFrame] = field(default_factory=dict)
    dividend: dict[str, pd.DataFrame] = field(default_factory=dict)
    financial: dict[str, pd.DataFrame] = field(default_factory=dict)


class ScreenerContext:
    """选股策略上下文，提供行情数据、指标计算等接口供策略调用。"""

    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        current_idx: int,
        frequency: str = "daily",
        weekly_data: dict[str, pd.DataFrame] | None = None,
        monthly_data: dict[str, pd.DataFrame] | None = None,
        valuation_data: dict[str, pd.DataFrame] | None = None,
        dividend_data: dict[str, pd.DataFrame] | None = None,
        financial_data: dict[str, pd.DataFrame] | None = None,
        *,
        market_data: MarketData | None = None,
    ):
        if market_data is not None:
            self._daily_data = market_data.daily
            self._weekly_data = market_data.weekly
            self._monthly_data = market_data.monthly
            self._valuation_data = market_data.valuation
            self._dividend_data = market_data.dividend
            self._financial_data = market_data.financial
        else:
            self._daily_data = stock_data
            self._weekly_data = weekly_data or {}
            self._monthly_data = monthly_data or {}
            self._valuation_data = valuation_data or {}
            self._dividend_data = dividend_data or {}
            self._financial_data = financial_data or {}
        self._current_idx = current_idx
        self._frequency = frequency
        self._indicator_cache: dict[str, pd.DataFrame] = {}
        self._precomputed_cache: dict[str, pd.DataFrame | None] = {}

        ref_sym = next(iter(self._daily_data))
        self._current_date = self._daily_data[ref_sym].iloc[current_idx]["date"]

        self._period_idx_cache: dict[str, int] = {}

    def _get_data_for_freq(
        self, symbol: str, freq: str | None = None
    ) -> tuple[pd.DataFrame | None, int]:
        # 根据频率选择对应数据源：daily直接用原始索引，weekly/monthly需查找当前日期对应的周期行
        f = freq or self._frequency
        if f == "daily":
            df = self._daily_data.get(symbol)
            return df, self._current_idx
        source = self._weekly_data if f == "weekly" else self._monthly_data
        df = source.get(symbol)
        if df is None or df.empty:
            return None, -1
        cache_key = f"{symbol}_{f}"
        if cache_key in self._period_idx_cache:
            return df, self._period_idx_cache[cache_key]
        mask = df["date"] <= self._current_date
        if not mask.any():
            self._period_idx_cache[cache_key] = -1
            return df, -1
        idx = mask.values.nonzero()[0][-1]
        self._period_idx_cache[cache_key] = idx
        return df, idx

    @property
    def current_date(self) -> str:
        return self._current_date

    def get_price(self, symbol: str, period: str | None = None) -> dict | None:
        df, idx = self._get_data_for_freq(symbol, period)
        if df is None or idx < 0 or idx >= len(df):
            return None
        return df.iloc[idx].to_dict()

    def get_history(self, symbol: str, n: int) -> list[dict]:
        df, idx = self._get_data_for_freq(symbol)
        if df is None or idx < 0:
            return []
        start = max(0, idx - n + 1)
        end = idx + 1
        return df.iloc[start:end].to_dict(orient="records")

    def get_valuation(self, symbol: str) -> dict | None:
        df = self._valuation_data.get(symbol)
        if df is None or df.empty:
            return None
        dates = df["date"]
        if len(dates) > 0 and not isinstance(dates.iloc[0], str):
            dates = dates.astype(str)
        mask = dates <= self._current_date
        if not mask.any():
            return None
        row = df.loc[mask].iloc[-1]
        result = {}
        for col in df.columns:
            if col == "date":
                result[col] = row[col]
                continue
            val = row[col]
            if isinstance(val, float) and math.isnan(val):
                sub_mask = mask & df[col].notna()
                if sub_mask.any():
                    result[col] = float(df.loc[sub_mask, col].iloc[-1])
                else:
                    result[col] = None
            else:
                result[col] = float(val) if val is not None else None
        return result

    def get_dividend(self, symbol: str) -> pd.DataFrame | None:
        df = self._dividend_data.get(symbol)
        if df is None or df.empty:
            return None
        return df

    def get_financial(self, symbol: str) -> dict | None:
        df = self._financial_data.get(symbol)
        if df is None or df.empty:
            return None
        dates = df["报告期"]
        if len(dates) > 0 and not isinstance(dates.iloc[0], str):
            dates = dates.astype(str)
        mask = dates <= self._current_date
        if not mask.any():
            return None
        row = df.loc[mask].iloc[-1]
        result = {}
        for col in df.columns:
            if col in ("报告期", "股票代码", "股票简称", "所处行业", "最新公告日期"):
                result[col] = row[col]
                continue
            val = row[col]
            if isinstance(val, float) and math.isnan(val):
                result[col] = None
            else:
                result[col] = float(val) if isinstance(val, (int, float)) else val
        return result

    def _get_precomputed(self, symbol: str, freq: str) -> pd.DataFrame | None:
        cache_key = f"{symbol}_{freq}"
        if cache_key not in self._precomputed_cache:
            df = load_indicators(symbol, freq)
            if df is not None:
                df = df.sort_values("date").reset_index(drop=True)
            self._precomputed_cache[cache_key] = df
        return self._precomputed_cache[cache_key]

    def _precomputed_value(self, symbol: str, freq: str, col: str) -> float | None:
        df, idx = self._get_data_for_freq(symbol, freq)
        if df is None or idx < 0:
            return None
        current_date = df.iloc[idx]["date"]
        pre_df = self._get_precomputed(symbol, freq)
        if pre_df is None or col not in pre_df.columns:
            return None
        mask = pre_df["date"] <= current_date
        if not mask.any():
            return None
        val = pre_df.loc[mask, col].iloc[-1]
        return None if (isinstance(val, float) and math.isnan(val)) else float(val)

    def indicator(
        self, symbol: str, ind_type: str, *args, period: str | None = None
    ) -> float | None:
        freq = period or self._frequency

        if ind_type == "ma":
            window = args[0] if args else 5
            val = self._precomputed_value(symbol, freq, f"ma{window}")
            if val is not None:
                return val
        elif ind_type == "macd":
            field_name = args[0] if args else "dif"
            val = self._precomputed_value(symbol, freq, field_name)
            if val is not None:
                return val
        elif ind_type == "kdj":
            field_name = args[0] if args else "k"
            val = self._precomputed_value(symbol, freq, field_name)
            if val is not None:
                return val
        elif ind_type == "boll":
            field_name = args[0] if args else "boll_mid"
            val = self._precomputed_value(symbol, freq, field_name)
            if val is not None:
                return val

        df, idx = self._get_data_for_freq(symbol, freq)
        if df is None or idx < 0:
            return None
        data_up_to = df.iloc[: idx + 1]
        if len(data_up_to) < 2:
            return None

        if ind_type == "ma":
            window = args[0] if args else 5
            cache_key = f"{symbol}_{freq}_ma_{window}"
            if cache_key not in self._indicator_cache:
                computed = calc_ma(data_up_to, windows=[window])
                self._indicator_cache[cache_key] = computed.sort_values(
                    "date"
                ).reset_index(drop=True)
            result_df = self._indicator_cache[cache_key]
            col = f"ma{window}"
            if col not in result_df.columns:
                return None
            val = result_df[col].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "macd":
            field_name = args[0] if args else "dif"
            cache_key = f"{symbol}_{freq}_macd"
            if cache_key not in self._indicator_cache:
                computed = calc_macd(data_up_to)
                self._indicator_cache[cache_key] = computed.sort_values(
                    "date"
                ).reset_index(drop=True)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            val = result_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "kdj":
            field_name = args[0] if args else "k"
            cache_key = f"{symbol}_{freq}_kdj"
            if cache_key not in self._indicator_cache:
                computed = calc_kdj(data_up_to)
                self._indicator_cache[cache_key] = computed.sort_values(
                    "date"
                ).reset_index(drop=True)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            val = result_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "boll":
            field_name = args[0] if args else "boll_mid"
            cache_key = f"{symbol}_{freq}_boll"
            if cache_key not in self._indicator_cache:
                computed = calc_boll(data_up_to)
                self._indicator_cache[cache_key] = computed.sort_values(
                    "date"
                ).reset_index(drop=True)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            val = result_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        return None


class TraderContext(ScreenerContext):
    """交易策略上下文，继承ScreenerContext并增加下单、持仓查询等交易接口。"""

    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        current_idx: int,
        portfolio: Portfolio,
        broker_submit,
        selected_symbols: list[str],
        days_since_rebalance: int = 0,
        weekly_data: dict[str, pd.DataFrame] | None = None,
        monthly_data: dict[str, pd.DataFrame] | None = None,
        valuation_data: dict[str, pd.DataFrame] | None = None,
        dividend_data: dict[str, pd.DataFrame] | None = None,
        financial_data: dict[str, pd.DataFrame] | None = None,
        target_symbols: list[str] | None = None,
        new_symbols: list[str] | None = None,
        on_remove_target: callable = None,
        *,
        market_data: MarketData | None = None,
    ):
        super().__init__(
            stock_data,
            current_idx,
            "daily",
            weekly_data,
            monthly_data,
            valuation_data,
            dividend_data,
            financial_data,
            market_data=market_data,
        )
        self._portfolio = portfolio
        self._broker_submit = broker_submit
        self.selected_symbols = selected_symbols
        self.days_since_rebalance = days_since_rebalance
        self.target_symbols = target_symbols or []
        self.new_symbols = new_symbols or []
        self._on_remove_target = on_remove_target

    def remove_target(self, symbol: str):
        """Seller 调用：平仓后从 target_symbols 中移除，通知引擎更新累计池。"""
        if self._on_remove_target:
            self._on_remove_target(symbol)
        if symbol in self.target_symbols:
            self.target_symbols.remove(symbol)

    @property
    def available_cash(self) -> float:
        return self._portfolio.cash

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
