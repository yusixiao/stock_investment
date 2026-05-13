"""回测引擎基类 — 封装 BacktestEngine 和 BuySellEngine 的共享逻辑。"""

import logging
from datetime import date as _date
from typing import Callable

import pandas as pd
from services.backtest.base import ScreenerStrategy
from services.backtest.context import ScreenerContext, MarketData
from services.stock_data import aggregate_kline

logger = logging.getLogger(__name__)


def parse_screen_result(result) -> tuple[list[str], dict[str, str]]:
    """统一解析筛选结果，支持 list[str] 和 list[dict] 两种格式。
    返回 (symbols, match_date_map)。
    """
    symbols = []
    match_date_map = {}
    for item in result:
        if isinstance(item, dict):
            symbols.append(item["symbol"])
            if "match_date" in item:
                match_date_map[item["symbol"]] = item["match_date"]
        else:
            symbols.append(item)
    return symbols, match_date_map


class BaseEngine:
    """回测引擎基类，提供数据预处理、周期缓存、选股上下文构建等公共能力。"""

    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        screeners: list[ScreenerStrategy] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        join_modes: list[str] | None = None,
        valuation_data: dict[str, pd.DataFrame] | None = None,
        dividend_data: dict[str, pd.DataFrame] | None = None,
        financial_data: dict[str, pd.DataFrame] | None = None,
    ):
        self._stock_data = {}
        for sym, df in stock_data.items():
            self._stock_data[sym] = df.sort_values("date").reset_index(drop=True)

        self._screeners = screeners or []
        self._on_progress = on_progress
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

        self._market_data = MarketData(
            daily=self._stock_data,
            weekly=self._weekly_data,
            monthly=self._monthly_data,
            valuation=self._valuation_data,
            dividend=self._dividend_data,
            financial=self._financial_data,
        )

    def _report(self, current: int, total: int, phase: str):
        if self._on_progress:
            self._on_progress(current, total, phase)

    def _precompute_periods(self):
        """预计算周线/月线数据，避免回测循环中重复聚合。"""
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

    def _make_screener_ctx(
        self, screener: ScreenerStrategy, idx: int
    ) -> ScreenerContext:
        return ScreenerContext(
            stock_data=self._stock_data,
            current_idx=idx,
            frequency=getattr(screener, "frequency", "daily"),
            market_data=self._market_data,
        )

    def _period_key(self, date_str: str, freq: str) -> str:
        """根据频率生成周期key: monthly→'2024-01', weekly→'2024-W03', daily→'2024-01-15'。"""
        if freq == "monthly":
            return date_str[:7]
        if freq == "weekly":
            dt = _date.fromisoformat(date_str)
            yr, wk, _ = dt.isocalendar()
            return f"{yr}-W{wk:02d}"
        return date_str

    def _build_bar_data(self, idx: int) -> tuple[dict[str, dict], dict[str, float]]:
        """构建当前bar的价格数据: 返回 (current_bars, current_prices)。"""
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
        return current_bars, current_prices

    def _run_screeners_at(
        self,
        idx: int,
        current_date: str,
        available_symbols: list[str],
        screener_cache: dict[int, list[str]],
        prev_period_keys: dict[int, str],
    ) -> set[str]:
        """在指定 bar 上执行所有 screener 并合并结果，利用周期缓存避免重复执行。
        返回合并后的 symbol set。
        """
        screener_sets: list[set[str]] = []
        for si, screener in enumerate(self._screeners):
            freq = getattr(screener, "frequency", "daily")
            pk = self._period_key(current_date, freq)
            need_run = (si not in prev_period_keys) or (pk != prev_period_keys[si])
            if need_run:
                ctx = self._make_screener_ctx(screener, idx)
                raw_result = screener.screen(ctx, list(available_symbols))
                symbols, _ = parse_screen_result(raw_result)
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

        return merged_set
