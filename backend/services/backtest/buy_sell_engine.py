from typing import Callable

import pandas as pd
from services.backtest.base import ScreenerStrategy, BuyStrategy, SellStrategy
from services.backtest.broker import Broker
from services.backtest.context import ScreenerContext, TraderContext
from services.backtest.analyzer import compute_metrics
from services.stock_data import aggregate_kline


class BuySellEngine:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        screeners: list[ScreenerStrategy] | None = None,
        buyer: BuyStrategy | None = None,
        seller: SellStrategy | None = None,
        initial_capital: float = 1_000_000,
        commission_rate: float = 0.0003,
        slippage: float = 0.002,
        on_progress: Callable[[int, int, str], None] | None = None,
        signal_table: dict[str, list[str]] | None = None,
        valuation_data: dict[str, pd.DataFrame] | None = None,
        dividend_data: dict[str, pd.DataFrame] | None = None,
        financial_data: dict[str, pd.DataFrame] | None = None,
        join_modes: list[str] | None = None,
    ):
        self._stock_data = {}
        for sym, df in stock_data.items():
            self._stock_data[sym] = df.sort_values("date").reset_index(drop=True)

        self._screeners = screeners or []
        self._buyer = buyer
        self._seller = seller
        self._initial_capital = initial_capital
        self._commission_rate = commission_rate
        self._slippage = slippage
        self._on_progress = on_progress
        self._signal_table = signal_table
        self._valuation_data = valuation_data or {}
        self._dividend_data = dividend_data or {}
        self._financial_data = financial_data or {}
        self._all_symbols = list(self._stock_data.keys())

        n = max(0, len(self._screeners) - 1)
        self._join_modes = (join_modes or [])[:n]
        while len(self._join_modes) < n:
            self._join_modes.append("independent")

        self._weekly_data: dict[str, pd.DataFrame] = {}
        self._monthly_data: dict[str, pd.DataFrame] = {}
        self._precompute_periods()

    def _report(self, current: int, total: int, phase: str):
        if self._on_progress:
            self._on_progress(current, total, phase)

    def _precompute_periods(self):
        needs_weekly = any(
            getattr(s, "frequency", "daily") == "weekly" for s in self._screeners
        )
        needs_monthly = any(
            getattr(s, "frequency", "daily") == "monthly" for s in self._screeners
        )
        if not needs_weekly and not needs_monthly:
            return
        total = len(self._stock_data)
        count = 0
        for sym, df in self._stock_data.items():
            if needs_weekly:
                self._weekly_data[sym] = aggregate_kline(df, period="weekly")
            if needs_monthly:
                self._monthly_data[sym] = aggregate_kline(df, period="monthly")
            count += 1
            if count % 500 == 0 or count == total:
                self._report(count, total, "预计算周期数据")

    def _period_key(self, date_str: str, freq: str) -> str:
        if freq == "monthly":
            return date_str[:7]
        if freq == "weekly":
            from datetime import date as _date
            dt = _date.fromisoformat(date_str)
            yr, wk, _ = dt.isocalendar()
            return f"{yr}-W{wk:02d}"
        return date_str

    def _make_screener_ctx(self, screener: ScreenerStrategy, idx: int) -> ScreenerContext:
        return ScreenerContext(
            stock_data=self._stock_data,
            current_idx=idx,
            frequency=getattr(screener, "frequency", "daily"),
            weekly_data=self._weekly_data,
            monthly_data=self._monthly_data,
            valuation_data=self._valuation_data,
            dividend_data=self._dividend_data,
            financial_data=self._financial_data,
        )

    def _parse_screen_result(self, result):
        symbols = []
        for item in result:
            if isinstance(item, dict):
                symbols.append(item["symbol"])
            else:
                symbols.append(item)
        return symbols

    def run(self) -> dict:
        broker = Broker(
            initial_capital=self._initial_capital,
            commission_rate=self._commission_rate,
            slippage=self._slippage,
        )

        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        n_bars = len(ref_df)

        equity_curve = []
        prev_closes: dict[str, float] = {}
        screener_cache: dict[int, list[str]] = {}
        prev_period_keys: dict[int, str] = {}

        for idx in range(n_bars):
            if idx % 10 == 0 or idx == n_bars - 1:
                self._report(idx + 1, n_bars, "回测中")

            current_bars = {}
            current_prices = {}
            for sym, df in self._stock_data.items():
                if idx < len(df):
                    row = df.iloc[idx]
                    current_bars[sym] = {
                        "open": row["open"],
                        "close": row["close"],
                        "high": row["high"],
                        "low": row["low"],
                    }
                    current_prices[sym] = row["close"]

            if idx > 0:
                broker.fill_orders(ref_df.iloc[idx]["date"], current_bars, prev_closes)

            current_date = ref_df.iloc[idx]["date"]
            available_symbols = [s for s in self._all_symbols if s in current_bars]

            if self._signal_table is not None:
                selected_symbols = self._signal_table.get(current_date, [])
            elif self._screeners:
                screener_sets: list[set[str]] = []
                for si, screener in enumerate(self._screeners):
                    freq = getattr(screener, "frequency", "daily")
                    pk = self._period_key(current_date, freq)
                    need_run = (si not in prev_period_keys) or (pk != prev_period_keys[si])
                    if need_run:
                        ctx = self._make_screener_ctx(screener, idx)
                        raw_result = screener.screen(ctx, list(available_symbols))
                        symbols = self._parse_screen_result(raw_result)
                        screener_cache[si] = list(symbols)
                        prev_period_keys[si] = pk
                    screener_sets.append(set(screener_cache.get(si, [])))

                merged_set = screener_sets[0] if screener_sets else set(available_symbols)
                for i, jm in enumerate(self._join_modes):
                    next_set = screener_sets[i + 1]
                    if jm == "correlated":
                        merged_set = merged_set & next_set
                    else:
                        merged_set = merged_set | next_set
                selected_symbols = [s for s in available_symbols if s in merged_set]
            else:
                selected_symbols = list(available_symbols)

            trader_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=selected_symbols,
                days_since_rebalance=0,
                weekly_data=self._weekly_data,
                monthly_data=self._monthly_data,
                valuation_data=self._valuation_data,
                dividend_data=self._dividend_data,
                financial_data=self._financial_data,
            )

            if self._seller:
                try:
                    self._seller.on_bar(trader_ctx)
                except Exception:
                    pass

            if selected_symbols and self._buyer:
                try:
                    self._buyer.on_bar(trader_ctx)
                except Exception:
                    pass

            snap = broker.portfolio.snapshot(current_date, current_prices)
            equity_curve.append(snap)

            prev_closes = dict(current_prices)

        metrics = compute_metrics(equity_curve, broker.all_trades, self._initial_capital)

        return {
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": broker.all_trades,
        }
