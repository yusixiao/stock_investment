"""单一回测引擎(Phase 3.3 新增,Phase 6 替换旧 engine.py + buy_sell_engine.py)。

设计目标(plan §3.3 / spec line 347-416):
- 单一执行路径,统一驱动 ``Strategy``(screen + on_buy + on_sell 三钩子)
- 频率感知:``screen()`` 仅在 strategy.frequency 周期切换时跑,缓存上一次结果
- 累计目标池(target_symbols):跨 bar 单调累积,sell 通过 ctx.remove_target 移除
- 执行顺序:fill_orders(T+1)→ screen(周期切换时)→ on_sell → on_buy → snapshot
- 决策日志:DecisionLogSink 由本类构造,Engine 不直写,日志由 Strategy 通过 ctx 调用
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Callable

import pandas as pd

import copy

from services.backtest.analyzer import compute_metrics, pair_round_trips
from services.backtest.broker import Broker
from services.backtest.context import Context, ScreenContext
from services.backtest.date_utils import format_match_date
from services.backtest.decision_log import DecisionLogSink
from services.backtest.market_data import MarketData
from strategies.base import Strategy


class BacktestEngine:
    """单路径回测引擎。"""

    def __init__(
        self,
        strategy: Strategy,
        stock_data: dict[str, pd.DataFrame],
        valuation_data: dict | None = None,
        dividend_data: dict | None = None,
        financial_data: dict | None = None,
        balance_data: dict | None = None,
        cashflow_data: dict | None = None,
        income_data: dict | None = None,
        weekly_data: dict | None = None,
        monthly_data: dict | None = None,
        iter_start: int | None = None,
        iter_end: int | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        log_dir: Path | None = None,
        enable_decision_log: bool = True,
    ):
        self._strategy = strategy
        # 通过 inspect.signature 自动取 Broker.__init__ 接受的关键字参数,
        # 这样未来 Broker 新增 kwarg(如 price_func)无需改本类
        broker_params = inspect.signature(Broker.__init__).parameters
        broker_kwargs = {
            k: v
            for k, v in strategy.settings.items()
            if k in broker_params and k != "self"
        }
        self._broker = Broker(**broker_kwargs)
        self._initial_capital = broker_kwargs.get("initial_capital", 1_000_000)

        self._market_data = MarketData(
            stock_data=stock_data,
            frequency=strategy.frequency,
            valuation=valuation_data,
            dividend=dividend_data,
            financial=financial_data,
            balance=balance_data,
            cashflow=cashflow_data,
            income=income_data,
            weekly_data=weekly_data,
            monthly_data=monthly_data,
        )
        self._log_sink = DecisionLogSink(log_dir, enabled=enable_decision_log)
        self._on_progress = on_progress
        self._all_symbols = list(stock_data.keys())

        # 迭代窗口:None 表示全历史。Engine 主循环只在 [iter_start, iter_end] 内
        # 调 screen / on_buy / on_sell;数据查询(get_history / get_indicator)
        # 仍可走全历史,因此长窗口指标(月线 MA20)在短 lookback 下也能正确计算。
        n = len(self._market_data.dates)
        self._iter_start = 0 if iter_start is None else max(0, iter_start)
        self._iter_end = (n - 1) if iter_end is None else min(n - 1, iter_end)

    # ---------- 内部:基于 MarketData 派生 bar 视图 ----------

    def _build_bar(self, idx: int) -> tuple[dict[str, dict], dict[str, float]]:
        """返回当前 bar 在所有 symbol 上的 OHLC bar 与 close 价格表。

        热路径:每根 bar 调用一次,内部对 N_symbols 全量遍历。
        使用 ``MarketData.get_bar_at(strict=True)`` 走 numpy 快速路径,
        相比旧 get_price + to_dict 路径 9.6x 加速(~12µs → ~1.2µs / call)。
        """
        bars: dict[str, dict] = {}
        prices: dict[str, float] = {}
        get_bar = self._market_data.get_bar_at  # local 缓存属性查找
        for sym in self._all_symbols:
            bar = get_bar(sym, idx, period="daily", strict=True)
            if bar is None:
                continue
            close = bar["close"]
            bars[sym] = {
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": close,
                # volume 透传到 broker;停牌填充日 volume=0 → broker 拒单
                "volume": bar.get("volume", 0.0),
            }
            prices[sym] = close
        return bars, prices

    # ---------- 主循环 ----------

    def run(self) -> dict:
        dates = self._market_data.dates
        n_bars = len(dates)
        iter_start = self._iter_start
        iter_end = self._iter_end
        # 迭代步数(供 progress 显示)= [iter_start, iter_end] 闭区间长度
        n_iter = max(0, iter_end - iter_start + 1)

        # 起始 flow 事件:记录策略类、参数与数据范围,便于离线追溯
        if self._log_sink.enabled and n_bars > 0 and n_iter > 0:
            self._log_sink.log_flow(
                "engine.run.start",
                idx=iter_start,
                ts=dates[iter_start],
                strategy=type(self._strategy).__name__,
                frequency=getattr(self._strategy, "frequency", ""),
                symbols=len(self._all_symbols),
                bars=n_iter,
                full_history_bars=n_bars,
                start_date=dates[iter_start],
                end_date=dates[iter_end],
                params={
                    k: getattr(self._strategy.p, k, None)
                    for k in getattr(self._strategy, "params", {})
                },
            )

        target_symbols: set[str] = set()
        screener_cache: list[str] = []
        prev_period_key: str | None = None
        prev_closes: dict[str, float] = {}
        equity_curve: list[dict] = []
        progress_done = 0

        for idx in range(iter_start, iter_end + 1):
            current_date = dates[idx]
            current_bars, current_prices = self._build_bar(idx)

            # 1) T+1 撮合:用今日 bar 填昨日挂单,prev_closes 仅用于涨跌停判定
            if idx > iter_start and self._broker.pending_orders:
                fills = self._broker.fill_orders(
                    current_date, current_bars, prev_closes
                )
                # 把成交事件写入 exec.jsonl(策略侧无法直接捕获 T+1 撮合)
                for trade in fills:
                    self._log_sink.log_exec(
                        trade["direction"],
                        trade["symbol"],
                        idx=idx,
                        ts=current_date,
                        shares=int(trade["shares"]),
                        price=float(trade["price"]),
                        note=f"commission={trade['commission']:.2f},tax={trade.get('tax', 0):.2f}",
                    )

            ctx = Context(
                strategy=self._strategy,
                idx=idx,
                broker=self._broker,
                market_data=self._market_data,
                log_sink=self._log_sink,
            )

            # 2) screen 仅在 frequency 周期切换时跑,跨周期沿用 cache
            pk = format_match_date(current_date, self._strategy.frequency)
            if pk != prev_period_key:
                screener_cache = list(
                    self._strategy.screen(ctx, list(self._all_symbols))
                )
                prev_period_key = pk

            # 3) 累计目标池:仅当今日有 bar 的 symbol 才能成为新目标
            today_signals = [s for s in screener_cache if s in current_bars]
            new_symbols = [s for s in today_signals if s not in target_symbols]
            target_symbols.update(new_symbols)
            ctx.set_pool(
                target_symbols,
                new_symbols,
                remove_callback=target_symbols.discard,
            )

            # 4) sell 先于 buy,Broker 自身禁止透支
            self._strategy.on_sell(ctx)
            self._strategy.on_buy(ctx)

            # 5) 快照 + prev_closes 滚动
            equity_curve.append(
                self._broker.portfolio.snapshot(current_date, current_prices)
            )
            prev_closes = dict(current_prices)

            progress_done += 1
            if self._on_progress:
                self._on_progress(progress_done, n_iter)

        # 收尾 flow 事件:总交易笔数 + 累计目标池大小
        if self._log_sink.enabled and n_iter > 0:
            self._log_sink.log_flow(
                "engine.run.done",
                idx=iter_end,
                ts=dates[iter_end],
                trades=len(self._broker.all_trades),
                target_pool=len(target_symbols),
                final_cash=float(self._broker.portfolio.cash),
            )
        # 落盘日志缓冲
        self._log_sink.flush()

        # trades 输出为 round-trip(buy/sell 配对),前端按此 schema 渲染。
        # 单边事件保留在 raw_trades,便于审计与回放。
        round_trips = pair_round_trips(self._broker.all_trades)
        # end_prices:每个交易过的 symbol 在 iter_end 当天的收盘价(strict=False
        # 允许非交易日回退到最近一个交易日)。前端用来计算未实现盈亏 / 当前价。
        traded_symbols = {t["symbol"] for t in self._broker.all_trades}
        end_prices: dict[str, float] = {}
        for sym in traded_symbols:
            bar = self._market_data.get_bar_at(
                sym, self._iter_end, period="daily", strict=False
            )
            if bar is not None:
                end_prices[sym] = float(bar["close"])
        return {
            "metrics": compute_metrics(
                equity_curve, self._broker.all_trades, self._initial_capital
            ),
            "equity_curve": equity_curve,
            "trades": round_trips,
            "raw_trades": self._broker.all_trades,
            "end_prices": end_prices,
            "log_dir": str(self._log_sink.log_dir) if self._log_sink.enabled else None,
        }

    # ---------- 选股雷达扫描(无 broker / 仅收集 hits + factors) ----------

    def run_scan(self) -> dict:
        """选股回测扫描(策略雷达专用)。

        语义:窗口内每根 bar 调用 ``strategy.screen()``,记录命中事件 +
        helper 内通过 ``ctx.record_factor`` 收集的因子值快照。
        频率感知:周期未切换时复用上一次 screen 结果(不重算)。
        每个新周期开始时调用 ``ctx.reset_factors()`` 清空,以便 helper 重新记录。

        返回:
          {
            "events": {symbol: [(date, factors_dict), ...]},  # 每只股票的命中事件序列
            "dates": [date_str, ...],                          # 实际扫描日期
            "all_symbols_count": int,                          # 全市场扫描数量
          }
        """
        dates = self._market_data.dates
        n_bars = len(dates)
        iter_start = self._iter_start
        iter_end = self._iter_end
        n_iter = max(0, iter_end - iter_start + 1)
        events: dict[str, list[tuple[str, dict]]] = {}
        all_symbols = list(self._all_symbols)

        if n_bars == 0 or n_iter == 0:
            return {
                "events": {},
                "dates": [],
                "all_symbols_count": len(all_symbols),
            }

        # run_scan 也写决策日志:scan-radar 路由配 log_dir 后,helper 内的
        # log_pass/log_reject/log_flow 应当落盘(此前因 ScreenContext 是 no-op
        # 而完全丢失,2026-05-22 修复)
        if self._log_sink.enabled:
            self._log_sink.log_flow(
                "engine.scan.start",
                idx=iter_start,
                ts=dates[iter_start],
                strategy=type(self._strategy).__name__,
                frequency=getattr(self._strategy, "frequency", ""),
                symbols=len(all_symbols),
                bars=n_iter,
                start_date=dates[iter_start],
                end_date=dates[iter_end],
                params={
                    k: getattr(self._strategy.p, k, None)
                    for k in getattr(self._strategy, "params", {})
                },
            )

        prev_period_key: str | None = None
        progress_done = 0

        for idx in range(iter_start, iter_end + 1):
            current_date = dates[idx]
            pk = format_match_date(current_date, self._strategy.frequency)
            # 仅在频率周期切换时调一次 screen — 避免日内重复记录命中
            if pk != prev_period_key:
                ctx = ScreenContext(
                    market_data=self._market_data,
                    idx=idx,
                    strategy=self._strategy,
                    log_sink=self._log_sink,
                )
                ctx.reset_factors()
                hits = list(self._strategy.screen(ctx, all_symbols))
                for sym in hits:
                    snapshot = copy.deepcopy(ctx.get_factors(sym))
                    events.setdefault(sym, []).append((current_date, snapshot))
                prev_period_key = pk

            progress_done += 1
            if self._on_progress:
                self._on_progress(progress_done, n_iter)

        if self._log_sink.enabled:
            self._log_sink.log_flow(
                "engine.scan.done",
                idx=iter_end,
                ts=dates[iter_end],
                hit_symbols=len(events),
            )
        self._log_sink.flush()

        return {
            "events": events,
            "dates": list(dates[iter_start : iter_end + 1]),
            "all_symbols_count": len(all_symbols),
        }
