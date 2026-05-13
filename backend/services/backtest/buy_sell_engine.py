"""买卖回测引擎 — 基于 Screener 筛选 + Buyer/Seller 交易策略的回测执行器。"""

import logging
from typing import Callable

import pandas as pd
from services.backtest.base import ScreenerStrategy, BuyStrategy, SellStrategy
from services.backtest.broker import Broker
from services.backtest.context import TraderContext, MarketData
from services.backtest.analyzer import compute_metrics
from services.backtest.engine_base import BaseEngine, parse_screen_result

logger = logging.getLogger(__name__)


class BuySellEngine(BaseEngine):
    """买卖回测引擎。

    支持两种选股模式:
    - signal_table 模式: 直接使用预计算的信号表（日期->股票列表映射）
    - screener 模式: 每个周期动态执行筛选策略，支持多频率和周期缓存

    筛选出的股票交由 Buyer/Seller 策略执行买卖操作。
    """

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
        super().__init__(
            stock_data=stock_data,
            screeners=screeners,
            on_progress=on_progress,
            join_modes=join_modes,
            valuation_data=valuation_data,
            dividend_data=dividend_data,
            financial_data=financial_data,
        )
        self._buyer = buyer
        self._seller = seller
        self._initial_capital = initial_capital
        self._commission_rate = commission_rate
        self._slippage = slippage
        self._signal_table = signal_table

        logger.info(
            "BuySellEngine 初始化: symbols=%d, screeners=%d, signal_table=%s, capital=%.0f",
            len(self._all_symbols),
            len(self._screeners),
            "是" if self._signal_table is not None else "否",
            self._initial_capital,
        )

    def run(self) -> dict:
        """执行回测主循环，返回 metrics/equity_curve/trades。

        核心逻辑：维护 target_symbols 累计池。
        - 每日从 signal_table/screener 获取今日信号
        - 仅新增股票加入 target_symbols 并标记为 new_symbols
        - Seller 每日执行，可通过 ctx.remove_target 移除股票
        - Buyer 每日执行（DCA等策略需要持续跟踪买入计划）
        """
        mode_desc = (
            "signal_table" if self._signal_table is not None else "screener+trader"
        )
        logger.info("开始运行回测, 模式: %s", mode_desc)

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
        target_symbols: set[str] = set()

        for idx in range(n_bars):
            if idx % 10 == 0 or idx == n_bars - 1:
                self._report(idx + 1, n_bars, "回测中")

            current_bars, current_prices = self._build_bar_data(idx)

            if idx > 0:
                broker.fill_orders(ref_df.iloc[idx]["date"], current_bars, prev_closes)

            current_date = ref_df.iloc[idx]["date"]
            available_symbols = [s for s in self._all_symbols if s in current_bars]

            # --- 选股逻辑: 获取今日信号 ---
            today_signals = self._get_today_signals(
                idx, current_date, available_symbols, screener_cache, prev_period_keys
            )

            # --- 累计池逻辑: 仅新增股票触发 buyer ---
            new_symbols = [s for s in today_signals if s not in target_symbols]
            target_symbols.update(new_symbols)

            def on_remove_target(sym, _ts=target_symbols):
                _ts.discard(sym)

            # Seller 每日执行
            if self._seller:
                seller_ctx = self._make_trader_ctx(
                    idx, broker, target_symbols, new_symbols, on_remove_target
                )
                try:
                    self._seller.on_bar(seller_ctx)
                except Exception as e:
                    logger.warning(
                        "Seller 执行异常: date=%s, error=%s", current_date, e
                    )

            # Buyer 每日执行
            if self._buyer:
                buyer_ctx = self._make_trader_ctx(
                    idx, broker, target_symbols, new_symbols, on_remove_target
                )
                try:
                    self._buyer.on_bar(buyer_ctx)
                except Exception as e:
                    logger.warning("Buyer 执行异常: date=%s, error=%s", current_date, e)

            snap = broker.portfolio.snapshot(current_date, current_prices)
            equity_curve.append(snap)
            prev_closes = dict(current_prices)

        metrics = compute_metrics(
            equity_curve, broker.all_trades, self._initial_capital
        )

        logger.info(
            "回测完成: bars=%d, trades=%d, final_equity=%.2f",
            n_bars,
            len(broker.all_trades),
            equity_curve[-1]["total_value"] if equity_curve else 0,
        )

        return {
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": broker.all_trades,
        }

    def _get_today_signals(
        self,
        idx: int,
        current_date: str,
        available_symbols: list[str],
        screener_cache: dict[int, list[str]],
        prev_period_keys: dict[int, str],
    ) -> list[str]:
        """获取今日选股信号，支持 signal_table 和 screener 两种模式。"""
        if self._signal_table is not None:
            signals = self._signal_table.get(current_date, [])
            if signals:
                logger.debug(
                    "signal_table 命中: date=%s, count=%d", current_date, len(signals)
                )
            return signals

        if self._screeners:
            merged_set = self._run_screeners_at(
                idx, current_date, available_symbols, screener_cache, prev_period_keys
            )
            return [s for s in available_symbols if s in merged_set]

        return []

    def _make_trader_ctx(
        self,
        idx: int,
        broker: Broker,
        target_symbols: set[str],
        new_symbols: list[str],
        on_remove_target,
    ) -> TraderContext:
        return TraderContext(
            stock_data=self._stock_data,
            current_idx=idx,
            portfolio=broker.portfolio,
            broker_submit=broker.submit_order,
            selected_symbols=list(target_symbols),
            days_since_rebalance=0,
            market_data=self._market_data,
            target_symbols=list(target_symbols),
            new_symbols=list(new_symbols),
            on_remove_target=on_remove_target,
        )
