import logging
from typing import Callable

import pandas as pd
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.broker import Broker
from services.backtest.context import ScreenerContext, TraderContext, MarketData
from services.backtest.analyzer import compute_metrics
from services.backtest.engine_base import BaseEngine, parse_screen_result
from services.backtest.date_utils import (
    format_match_date,
    date_belongs_to,
    detect_frequency,
    FREQ_ORDER,
)
from services.stock_data import aggregate_kline

logger = logging.getLogger(__name__)


class BacktestEngine(BaseEngine):
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        screeners: list[ScreenerStrategy],
        trader: TraderStrategy | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        join_modes: list[str] | None = None,
        valuation_data: dict[str, pd.DataFrame] | None = None,
        dividend_data: dict[str, pd.DataFrame] | None = None,
        financial_data: dict[str, pd.DataFrame] | None = None,
        source_matches: dict[str, list[str]] | None = None,
    ):
        super().__init__(
            stock_data=stock_data,
            screeners=screeners,
            on_progress=on_progress,
            join_modes=join_modes,
            valuation_data=valuation_data,
            dividend_data=dividend_data,
            financial_data=financial_data,
        )
        self._trader = trader
        self._source_matches = source_matches
        logger.info(
            "Engine init: %d symbols, %d screeners, trader=%s, source_matches=%s",
            len(self._stock_data),
            len(self._screeners),
            trader.__class__.__name__ if trader else "None",
            f"{len(source_matches)} symbols" if source_matches else "None",
        )

    def _pipeline_finest_freq(self) -> str:
        best = "monthly"
        for s in self._screeners:
            f = getattr(s, "frequency", "daily")
            if FREQ_ORDER.get(f, 0) < FREQ_ORDER.get(best, 0):
                best = f
        return best

    def _finest_freq_in_result(self, result: dict[str, list[str]]) -> str:
        best = "yearly"
        for dates in result.values():
            for d in dates:
                f = detect_frequency(d)
                if FREQ_ORDER.get(f, 0) < FREQ_ORDER.get(best, 99):
                    best = f
        return best

    def _count_matches(self, result: dict[str, list[str]]) -> int:
        return sum(len(v) for v in result.values())

    def _union_results(
        self, a: dict[str, list[str]], b: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        merged = {}
        for sym in set(a) | set(b):
            dates_a = a.get(sym, [])
            dates_b = b.get(sym, [])
            combined = list(dates_a)
            for d in dates_b:
                if d not in combined:
                    combined.append(d)
            merged[sym] = combined
        return merged

    def _intersect_results(
        self,
        prev: dict[str, list[str]],
        curr: dict[str, list[str]],
        coarse_freq: str,
        pair_idx: int,
    ) -> dict[str, list[str]]:
        merged = {}
        common_syms = set(prev) & set(curr)
        for sym in common_syms:
            kept = []
            kept_set = set()
            for d_prev in prev[sym]:
                matched = any(
                    date_belongs_to(d_prev, d_curr) or date_belongs_to(d_curr, d_prev)
                    for d_curr in curr[sym]
                )
                if matched:
                    logger.debug('[Pair %d] %s: "%s" matched', pair_idx, sym, d_prev)
                    kept.append(d_prev)
                    kept_set.add(d_prev)
                else:
                    logger.debug('[Pair %d] %s: "%s" discarded', pair_idx, sym, d_prev)
            for d_curr in curr[sym]:
                if d_curr in kept_set:
                    continue
                matched = any(
                    date_belongs_to(d_curr, d_prev) or date_belongs_to(d_prev, d_curr)
                    for d_prev in prev[sym]
                )
                if matched:
                    logger.debug(
                        '[Pair %d] %s: "%s" matched (from curr)',
                        pair_idx,
                        sym,
                        d_curr,
                    )
                    kept.append(d_curr)
                    kept_set.add(d_curr)
                else:
                    logger.debug(
                        '[Pair %d] %s: "%s" discarded (from curr)',
                        pair_idx,
                        sym,
                        d_curr,
                    )
            if kept:
                merged[sym] = kept
        return merged

    def _filter_to_finest(
        self, merged: dict[str, list[str]], finest: str
    ) -> dict[str, list[str]]:
        finest_order = FREQ_ORDER[finest]
        filtered = {}
        for sym, dates in merged.items():
            kept = []
            for d in dates:
                f = detect_frequency(d)
                if FREQ_ORDER.get(f, 0) <= finest_order:
                    logger.debug('[Output] %s: "%s" (%s) kept', sym, d, f)
                    kept.append(d)
                else:
                    logger.debug('[Output] %s: "%s" (%s) discarded', sym, d, f)
            if kept:
                filtered[sym] = kept
        return filtered

    def _apply_source_matches(self, result: dict) -> dict:
        if self._source_matches is None:
            return result
        screened = result.get("screened_symbols")
        if screened is None:
            return result

        if isinstance(screened, list) and screened and isinstance(screened[0], str):
            filtered = [s for s in screened if s in self._source_matches]
            result["screened_symbols"] = filtered
            return result

        new_result = result.get("screened_symbols", [])
        merged = {}
        for item in new_result:
            sym = item["symbol"]
            if sym not in self._source_matches:
                continue
            src_dates = self._source_matches[sym]
            new_dates = item.get("match_dates", [])
            kept = []
            for nd in new_dates:
                for sd in src_dates:
                    if date_belongs_to(nd, sd) or date_belongs_to(sd, nd):
                        kept.append(nd)
                        break
            if kept:
                merged[sym] = kept

        filtered = []
        for sym, dates in merged.items():
            filtered.append({"symbol": sym, "match_dates": dates})
        filtered.sort(key=lambda x: x["match_dates"][-1], reverse=True)
        result["screened_symbols"] = filtered
        return result

    def run(self, mode: str = "auto") -> dict:
        if mode == "screen":
            logger.info("执行路径: screen(仅最新bar选股)")
            result = self._run_screener_only()
            return self._apply_source_matches(result)
        if self._trader is None:
            logger.info("执行路径: screener_backtest(选股回测)")
            result = self._run_screener_backtest()
            return self._apply_source_matches(result)
        logger.info("执行路径: backtest(完整回测)")
        return self._run_backtest()

    def _run_screener_only(self) -> dict:
        logger.info(
            "_run_screener_only: 开始, %d个策略, %d只股票",
            len(self._screeners),
            len(self._all_symbols),
        )
        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        last_idx = len(ref_df) - 1

        screener_sets: list[set[str]] = []
        total = len(self._screeners)
        for i, screener in enumerate(self._screeners):
            self._report(i + 1, total, f"选股中 ({screener.__class__.__name__})")
            ctx = self._make_screener_ctx(screener, last_idx)
            raw_result = screener.screen(ctx, list(self._all_symbols))
            symbols, _ = parse_screen_result(raw_result)
            screener_sets.append(set(symbols))

        merged = screener_sets[0] if screener_sets else set()
        for i, mode in enumerate(self._join_modes):
            next_set = screener_sets[i + 1]
            if mode == "correlated":
                merged = merged & next_set
            else:
                merged = merged | next_set

        logger.info("_run_screener_only: 完成, 选出%d只", len(merged))
        return {"screened_symbols": sorted(merged)}

    def _period_date(self, current_date: str, freq: str) -> str | None:
        if freq == "daily":
            return current_date
        source = self._weekly_data if freq == "weekly" else self._monthly_data
        ref_sym = self._all_symbols[0]
        df = source.get(ref_sym)
        if df is None or df.empty:
            return None
        mask = df["date"] <= current_date
        if not mask.any():
            return None
        idx = mask.values.nonzero()[0][-1]
        return df.iloc[idx]["date"]

    def _run_screener_backtest(self) -> dict:
        if not self._all_symbols:
            logger.warning("_run_screener_backtest: 无股票数据，返回空结果")
            return {"screened_symbols": []}
        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        n_bars = len(ref_df)
        logger.info(
            "_run_screener_backtest: 开始, %d bars, %d只股票",
            n_bars,
            len(self._all_symbols),
        )

        raw_results: dict[int, dict[str, list[str]]] = {
            si: {} for si in range(len(self._screeners))
        }
        screener_cache: dict[int, list[str]] = {}
        prev_period_keys: dict[int, str] = {}

        for idx in range(n_bars):
            if idx % 10 == 0 or idx == n_bars - 1:
                self._report(idx + 1, n_bars, "选股回测中")
            current_date = ref_df.iloc[idx]["date"]

            for si, screener in enumerate(self._screeners):
                freq = getattr(screener, "frequency", "daily")
                pk = self._period_key(current_date, freq)
                need_run = (si not in prev_period_keys) or (pk != prev_period_keys[si])

                if need_run:
                    ctx = self._make_screener_ctx(screener, idx)
                    raw_result = screener.screen(ctx, list(self._all_symbols))
                    symbols, custom_dates = parse_screen_result(raw_result)
                    screener_cache[si] = list(symbols)
                    prev_period_keys[si] = pk

                    record_date = self._period_date(current_date, freq)
                    if record_date is None:
                        continue
                    formatted = format_match_date(record_date, freq)
                    for sym in symbols:
                        custom = custom_dates.get(sym)
                        if custom:
                            date_to_record = format_match_date(custom, freq)
                        else:
                            date_to_record = formatted
                        history = raw_results[si].setdefault(sym, [])
                        if date_to_record not in history:
                            history.append(date_to_record)

        merged = raw_results[0] if raw_results else {}
        for i, jm in enumerate(self._join_modes):
            next_result = raw_results[i + 1]
            freq_prev = (
                getattr(self._screeners[i], "frequency", "daily")
                if i < len(self._screeners)
                else "daily"
            )
            freq_next = getattr(self._screeners[i + 1], "frequency", "daily")
            coarse = (
                freq_prev
                if FREQ_ORDER.get(freq_prev, 0) > FREQ_ORDER.get(freq_next, 0)
                else freq_next
            )
            if jm == "correlated":
                merged = self._intersect_results(merged, next_result, coarse, i)
            else:
                merged = self._union_results(merged, next_result)

        finest = self._pipeline_finest_freq()
        merged = self._filter_to_finest(merged, finest)

        result = []
        for sym, dates in merged.items():
            result.append({"symbol": sym, "match_dates": dates})
        result.sort(key=lambda x: x["match_dates"][-1], reverse=True)
        logger.info(
            "_run_screener_backtest: 完成, 选出%d只, 共%d条匹配",
            len(result),
            sum(len(r["match_dates"]) for r in result),
        )
        return {"screened_symbols": result}

    def _run_backtest(self) -> dict:
        settings = self._trader.settings
        logger.info(
            "_run_backtest: 开始, initial_capital=%.0f, commission=%.4f, slippage=%.4f",
            settings["initial_capital"],
            settings["commission_rate"],
            settings["slippage"],
        )
        if not self._all_symbols:
            logger.warning("_run_backtest: 无股票数据，返回空结果")
            return {"metrics": {}, "equity_curve": [], "trades": []}
        broker = Broker(
            initial_capital=settings["initial_capital"],
            commission_rate=settings["commission_rate"],
            slippage=settings["slippage"],
        )

        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        n_bars = len(ref_df)
        logger.info("_run_backtest: %d bars, %d只股票", n_bars, len(self._all_symbols))

        equity_curve = []
        days_since_rebalance = 0
        prev_closes: dict[str, float] = {}
        screener_cache: dict[int, list[str]] = {}
        prev_period_keys: dict[int, str] = {}

        for idx in range(n_bars):
            if idx % 10 == 0 or idx == n_bars - 1:
                self._report(idx + 1, n_bars, "回测中")

            current_bars, current_prices = self._build_bar_data(idx)

            if idx > 0:
                broker.fill_orders(ref_df.iloc[idx]["date"], current_bars, prev_closes)

            current_date = ref_df.iloc[idx]["date"]
            available_symbols = [s for s in self._all_symbols if s in current_bars]

            merged_set = self._run_screeners_at(
                idx, current_date, available_symbols, screener_cache, prev_period_keys
            )
            symbols = [s for s in available_symbols if s in merged_set]

            trader_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=symbols,
                days_since_rebalance=days_since_rebalance,
                market_data=self._market_data,
            )

            try:
                self._trader.on_bar(trader_ctx)
            except Exception as e:
                logger.warning(
                    "Trader on_bar exception at %s: %s", ref_df.iloc[idx]["date"], e
                )

            days_since_rebalance = trader_ctx.days_since_rebalance + 1

            snap = broker.portfolio.snapshot(ref_df.iloc[idx]["date"], current_prices)
            equity_curve.append(snap)

            prev_closes = dict(current_prices)

        metrics = compute_metrics(
            equity_curve, broker.all_trades, settings["initial_capital"]
        )

        return {
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": broker.all_trades,
        }
