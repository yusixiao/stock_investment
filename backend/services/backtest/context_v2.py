"""单一 Context(Phase 3.1 新增,Phase 6 重命名为 context.py 替换旧实现)。

替代旧的 ScreenerContext + TraderContext 二分:
- 数据访问代理给 MarketData(T3.2)
- 持仓与下单代理给 Broker
- 决策日志代理给 DecisionLogSink,自动塞入 idx / ts / freq
- 累计池(target_symbols / new_symbols)由 Engine 通过 set_pool 注入
"""

from __future__ import annotations

from typing import Any, Callable


class Context:
    def __init__(self, *, strategy, idx: int, broker, market_data, log_sink):
        self.strategy = strategy
        self.current_idx = idx
        # market_data.dates 是回测时间轴(频率由 Engine 决定),
        # 一旦构造完成 current_date 即固化为该 bar 的时间戳
        self.current_date = market_data.dates[idx]
        self._broker = broker
        self._market_data = market_data
        self.log_sink = log_sink

        # 累计池默认空,Engine 在每个 bar 通过 set_pool 注入当前快照
        self.target_symbols: set[str] = set()
        self.new_symbols: list[str] = []
        self._remove_callback: Callable[[str], None] | None = None

    # ===== 累计池 =====
    def set_pool(
        self,
        target: set[str],
        new: list[str],
        *,
        remove_callback: Callable[[str], None],
    ) -> None:
        self.target_symbols = target
        self.new_symbols = new
        self._remove_callback = remove_callback

    def remove_target(self, symbol: str) -> None:
        # 未注入 callback 时静默忽略,便于策略单测脱离 Engine 运行
        if self._remove_callback:
            self._remove_callback(symbol)

    # ===== 数据访问(代理 market_data) =====
    def get_price(self, symbol: str, period: str = "daily"):
        return self._market_data.get_price(symbol, period=period, idx=self.current_idx)

    def get_history(self, symbol: str, n: int, period: str = "daily"):
        return self._market_data.get_history(
            symbol, n=n, period=period, idx=self.current_idx
        )

    def get_valuation(self, symbol: str):
        return self._market_data.get_valuation(symbol, date=self.current_date)

    def get_dividend(self, symbol: str):
        return self._market_data.get_dividend(symbol, date=self.current_date)

    def get_financial(self, symbol: str):
        return self._market_data.get_financial(symbol, date=self.current_date)

    def indicator(self, name: str, symbol: str, **kwargs):
        return self._market_data.indicator(name, symbol, idx=self.current_idx, **kwargs)

    # ===== 持仓与下单(代理 broker) =====
    @property
    def available_cash(self) -> float:
        return self._broker.portfolio.available_cash

    def get_position(self, symbol: str):
        return self._broker.portfolio.get_position(symbol)

    def get_positions(self):
        return self._broker.portfolio.positions

    def order_shares(self, symbol: str, shares: int):
        return self._broker.submit_order(
            symbol=symbol, shares=shares, date=self.current_date
        )

    def order_value(self, symbol: str, value: float):
        # 按当前 bar 收盘价折算股数,再向下取整到 100 股的整手
        price = self.get_price(symbol)
        if price is None:
            return None
        shares = int(value / price["close"]) // 100 * 100
        return self.order_shares(symbol, shares) if shares >= 100 else None

    def order_target_percent(self, symbol: str, target_pct: float):
        equity = self._broker.portfolio.equity(self.current_date)
        return self.order_value(symbol, equity * target_pct)

    # ===== 日志(代理 sink) =====
    def _common_log_kwargs(self) -> dict[str, Any]:
        return {
            "idx": self.current_idx,
            "ts": self.current_date,
            "freq": self.strategy.frequency,
        }

    def log_pass(self, symbol: str, stage: str, **values: Any) -> None:
        self.log_sink.log_pass(symbol, stage, **self._common_log_kwargs(), **values)

    def log_reject(
        self, symbol: str, stage: str, *, reason: str, **values: Any
    ) -> None:
        self.log_sink.log_reject(
            symbol, stage, reason=reason, **self._common_log_kwargs(), **values
        )

    def log_flow(self, stage: str, **counts: Any) -> None:
        self.log_sink.log_flow(
            stage, idx=self.current_idx, ts=self.current_date, **counts
        )

    def log_exec(
        self,
        action: str,
        symbol: str,
        *,
        shares: int,
        price: float,
        note: str = "",
    ) -> None:
        self.log_sink.log_exec(
            action,
            symbol,
            idx=self.current_idx,
            ts=self.current_date,
            shares=shares,
            price=price,
            note=note,
        )
