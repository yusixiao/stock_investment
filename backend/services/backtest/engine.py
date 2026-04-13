import pandas as pd
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.broker import Broker
from services.backtest.context import ScreenerContext, TraderContext
from services.backtest.analyzer import compute_metrics


class BacktestEngine:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        screeners: list[ScreenerStrategy],
        trader: TraderStrategy | None = None,
    ):
        self._stock_data = {}
        for sym, df in stock_data.items():
            self._stock_data[sym] = df.sort_values("date").reset_index(drop=True)

        self._screeners = screeners
        self._trader = trader
        self._all_symbols = list(self._stock_data.keys())

    def run(self) -> dict:
        if self._trader is None:
            return self._run_screener_only()
        return self._run_backtest()

    def _run_screener_only(self) -> dict:
        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        last_idx = len(ref_df) - 1
        symbols = list(self._all_symbols)
        for screener in self._screeners:
            ctx = ScreenerContext(self._stock_data, last_idx)
            symbols = screener.screen(ctx, symbols)
        return {"screened_symbols": symbols}

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
                ctx = ScreenerContext(self._stock_data, idx)
                symbols = screener.screen(ctx, symbols)

            trader_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=symbols,
                days_since_rebalance=days_since_rebalance,
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
