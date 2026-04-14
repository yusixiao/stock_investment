from typing import Callable

import pandas as pd
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.broker import Broker
from services.backtest.context import ScreenerContext, TraderContext
from services.backtest.analyzer import compute_metrics
from services.stock_data import aggregate_kline


class BacktestEngine:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        screeners: list[ScreenerStrategy],
        trader: TraderStrategy | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ):
        self._stock_data = {}
        for sym, df in stock_data.items():
            self._stock_data[sym] = df.sort_values("date").reset_index(drop=True)

        self._screeners = screeners
        self._trader = trader
        self._all_symbols = list(self._stock_data.keys())
        self._on_progress = on_progress

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

    def _make_screener_ctx(self, screener: ScreenerStrategy, idx: int) -> ScreenerContext:
        return ScreenerContext(
            stock_data=self._stock_data,
            current_idx=idx,
            frequency=getattr(screener, "frequency", "daily"),
            weekly_data=self._weekly_data,
            monthly_data=self._monthly_data,
        )

    def run(self, mode: str = "auto") -> dict:
        if mode == "screen":
            return self._run_screener_only()
        if self._trader is None:
            return self._run_screener_backtest()
        return self._run_backtest()

    def _run_screener_only(self) -> dict:
        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        last_idx = len(ref_df) - 1
        symbols = list(self._all_symbols)
        total = len(self._screeners)
        for i, screener in enumerate(self._screeners):
            self._report(i + 1, total, f"选股中 ({screener.__class__.__name__})")
            ctx = self._make_screener_ctx(screener, last_idx)
            symbols = screener.screen(ctx, symbols)
        return {"screened_symbols": symbols}

    def _run_screener_backtest(self) -> dict:
        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        n_bars = len(ref_df)

        match_history: dict[str, list[str]] = {}

        for idx in range(n_bars):
            if idx % 10 == 0 or idx == n_bars - 1:
                self._report(idx + 1, n_bars, "选股回测中")
            symbols = list(self._all_symbols)
            for screener in self._screeners:
                ctx = self._make_screener_ctx(screener, idx)
                symbols = screener.screen(ctx, symbols)
            if symbols:
                current_date = ref_df.iloc[idx]["date"]
                for sym in symbols:
                    match_history.setdefault(sym, []).append(current_date)

        result = []
        for sym, dates in match_history.items():
            result.append({"symbol": sym, "match_dates": dates})
        result.sort(key=lambda x: x["match_dates"][-1], reverse=True)
        return {"screened_symbols": result}

    def _run_backtest(self) -> dict:
        settings = self._trader.settings
        broker = Broker(
            initial_capital=settings["initial_capital"],
            commission_rate=settings["commission_rate"],
            slippage=settings["slippage"],
        )

        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        n_bars = len(ref_df)

        equity_curve = []
        days_since_rebalance = 0
        prev_closes: dict[str, float] = {}

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

            available_symbols = [s for s in self._all_symbols if s in current_bars]
            symbols = list(available_symbols)
            for screener in self._screeners:
                ctx = self._make_screener_ctx(screener, idx)
                symbols = screener.screen(ctx, symbols)

            trader_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=symbols,
                days_since_rebalance=days_since_rebalance,
                weekly_data=self._weekly_data,
                monthly_data=self._monthly_data,
            )

            try:
                self._trader.on_bar(trader_ctx)
            except Exception:
                pass

            days_since_rebalance = trader_ctx.days_since_rebalance + 1

            snap = broker.portfolio.snapshot(ref_df.iloc[idx]["date"], current_prices)
            equity_curve.append(snap)

            prev_closes = dict(current_prices)

        metrics = compute_metrics(equity_curve, broker.all_trades, settings["initial_capital"])

        return {
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": broker.all_trades,
        }
