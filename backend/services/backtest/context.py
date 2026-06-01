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

        # 因子收集(策略雷达 / 选股回测用):
        # helper 在筛选时用 record_factor(s, name, value) 记录策略实际用到的判断
        # 中间值,API 层在 hits 上读取 get_factors(s) 用于前端展示。
        # 回测主路径不需要快照,Engine 选股回测分支才会在每个 bar screen() 后
        # 把 hits 的 factors 拷贝出来,然后通过 reset_factors() 清空给下个 bar 用。
        self._factors: dict[str, dict[str, Any]] = {}

    # ===== 因子收集 =====
    def record_factor(self, symbol: str, name: str, value: Any) -> None:
        """记录某只股票在当前 bar 评估时的因子值(策略筛选用到的中间值)。
        多次记录同一 (symbol, name) 后值覆盖前值。"""
        bucket = self._factors.get(symbol)
        if bucket is None:
            bucket = {}
            self._factors[symbol] = bucket
        bucket[name] = value

    def get_factors(self, symbol: str) -> dict[str, Any]:
        """读当前 bar 已记录的因子。返回浅 copy 的 dict(策略雷达 engine
        会进一步深拷贝快照,普通调用方拿到的是只读视图即可)。"""
        return dict(self._factors.get(symbol, {}))

    def get_all_factors(self) -> dict[str, dict[str, Any]]:
        """读全部 symbol 的因子(Engine 选股回测分支批量取 hits 时使用)。"""
        return self._factors

    def reset_factors(self) -> None:
        """清空因子收集(Engine 在每个 bar screen() 之前调用,避免跨 bar 残留)。"""
        self._factors = {}

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

    def is_hk_connect(self, symbol: str) -> bool:
        """该 HK 股票当前是否港股通成分股(基于最新快照,非 point-in-time)。
        非 HK 标的恒返 False。⚠️ 接受 ~2-3% look-ahead 偏差。"""
        if not symbol or not symbol.endswith(".HK"):
            return False
        from services.hk_connect_updater import get_latest_hk_connect_codes

        code = symbol.split(".")[0]
        return code in get_latest_hk_connect_codes()

    def get_financial_annual(self, symbol: str):
        """仅取年报口径(REPORT_DATE = -12-31)。
        用于 ROE 等需要年化口径的指标,避免季报累计值在年中拉低门槛。"""
        return self._market_data.get_financial_annual(symbol, date=self.current_date)

    def get_balance(self, symbol: str):
        """资产负债表最近一期(任何报告期)。"""
        return self._market_data.get_balance(symbol, date=self.current_date)

    def get_balance_annual(self, symbol: str):
        """资产负债表最近一份年报(REPORT_DATE = -12-31)。"""
        return self._market_data.get_balance_annual(symbol, date=self.current_date)

    def get_cashflow(self, symbol: str):
        """现金流量表最近一期(任何报告期)。"""
        return self._market_data.get_cashflow(symbol, date=self.current_date)

    def get_cashflow_annual(self, symbol: str):
        """现金流量表最近一份年报(REPORT_DATE = -12-31)。"""
        return self._market_data.get_cashflow_annual(symbol, date=self.current_date)

    def get_financial_annual_history(self, symbol: str, n: int):
        """近 n 期年报(列表倒序,最新在 [0])。"""
        return self._market_data.get_financial_annual_history(
            symbol, date=self.current_date, n=n
        )

    def get_balance_annual_history(self, symbol: str, n: int):
        return self._market_data.get_balance_annual_history(
            symbol, date=self.current_date, n=n
        )

    def get_cashflow_annual_history(self, symbol: str, n: int):
        return self._market_data.get_cashflow_annual_history(
            symbol, date=self.current_date, n=n
        )

    def get_income_annual_history(self, symbol: str, n: int):
        return self._market_data.get_income_annual_history(
            symbol, date=self.current_date, n=n
        )

    def indicator(self, name: str, symbol: str, **kwargs):
        return self._market_data.indicator(name, symbol, idx=self.current_idx, **kwargs)

    def get_indicator(
        self, name: str, symbol: str, period: str = "daily", **kwargs
    ) -> float | None:
        """O(1) 查预算指标(不命中标准列时返回 None,helper 自行 fallback)。"""
        return self._market_data.get_indicator(
            name, symbol, idx=self.current_idx, period=period, **kwargs
        )

    # ===== 持仓与下单(代理 broker) =====
    @property
    def available_cash(self) -> float:
        return self._broker.portfolio.available_cash

    def get_position(self, symbol: str):
        return self._broker.portfolio.get_position(symbol)

    def get_positions(self):
        return self._broker.portfolio.positions

    def order_shares(self, symbol: str, shares: int):
        # 约定:正数为买入,负数为卖出。Broker.submit_order 不接受 date——
        # 成交日期由 Broker.fill_orders(date, ...) 在 T+1 撮合时记录
        if shares > 0:
            return self._broker.submit_order(
                symbol=symbol, shares=shares, direction="buy"
            )
        if shares < 0:
            return self._broker.submit_order(
                symbol=symbol, shares=-shares, direction="sell"
            )
        return None

    def order_value(self, symbol: str, value: float):
        # 按当前 bar 收盘价折算股数,再向下取整到 100 股的整手
        price = self.get_price(symbol)
        if price is None:
            return None
        shares = int(value / price["close"]) // 100 * 100
        return self.order_shares(symbol, shares) if shares >= 100 else None

    def order_target_percent(self, symbol: str, target_pct: float):
        # 语义:把 symbol 持仓**调整到** equity × target_pct,而非每次绝对加仓。
        # equity = cash + 所有持仓按当前 bar 收盘价的市值
        portfolio = self._broker.portfolio
        current_prices: dict[str, float] = {}
        for sym in portfolio.get_positions():
            price = self.get_price(sym)
            if price is not None:
                current_prices[sym] = price["close"]
        equity = portfolio.get_total_value(current_prices)

        price = self.get_price(symbol)
        if price is None:
            return None
        # 目标股数(整百)
        target_shares = int(equity * target_pct / price["close"]) // 100 * 100
        # 当前持仓股数
        pos = portfolio.get_position(symbol)
        held = pos["shares"] if pos else 0
        delta = target_shares - held
        if delta == 0:
            return None
        # delta < 100 股时不下单(同 order_value 的 100 股整手约束)
        if abs(delta) < 100:
            return None
        return self.order_shares(symbol, delta)

    # ===== 日志(代理 sink) =====
    def _common_log_kwargs(self) -> dict[str, Any]:
        return {
            "idx": self.current_idx,
            "ts": self.current_date,
            "freq": self.strategy.frequency,
        }

    def log_pass(self, symbol: str, stage: str, **values: Any) -> None:
        self.log_sink.log_pass(symbol, stage, **self._common_log_kwargs(), **values)

    def log_reject(self, symbol: str, stage: str, reason: str, **values: Any) -> None:
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


class ScreenContext:
    """选股阶段轻量 Context — 无 broker,可选写决策日志。

    用于:
    - /api/screener/run 这类一次性选股调用(不传 sink/strategy → 日志 no-op)
    - Engine.run_scan() 雷达扫描(传入 strategy + log_sink → 日志正常落盘,
      2026-05-22 修复 #ScreenContext-log-no-op-bug)

    与 Context 接口兼容(策略 .screen() 可直接复用)。
    """

    def __init__(
        self,
        *,
        market_data,
        idx: int,
        strategy=None,
        log_sink=None,
    ):
        self._market_data = market_data
        self.current_idx = idx
        self.current_date = market_data.dates[idx] if market_data.dates else None
        self.target_symbols: set[str] = set()
        self.new_symbols: list[str] = []
        # 决策日志:无 sink 时所有 log_* 静默,接近旧行为
        self.strategy = strategy
        self.log_sink = log_sink
        # 因子收集 — 与 Context 同语义,helper 函数靠这个统一接口写入,
        # 上层(/api/screener/run 或 scan-radar)读 get_factors / get_all_factors。
        self._factors: dict[str, dict[str, Any]] = {}

    def record_factor(self, symbol: str, name: str, value: Any) -> None:
        bucket = self._factors.get(symbol)
        if bucket is None:
            bucket = {}
            self._factors[symbol] = bucket
        bucket[name] = value

    def get_factors(self, symbol: str) -> dict[str, Any]:
        return dict(self._factors.get(symbol, {}))

    def get_all_factors(self) -> dict[str, dict[str, Any]]:
        return self._factors

    def reset_factors(self) -> None:
        self._factors = {}

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

    def is_hk_connect(self, symbol: str) -> bool:
        """该 HK 股票当前是否港股通成分股(基于最新快照,非 point-in-time)。
        非 HK 标的恒返 False。⚠️ 接受 ~2-3% look-ahead 偏差。"""
        if not symbol or not symbol.endswith(".HK"):
            return False
        from services.hk_connect_updater import get_latest_hk_connect_codes

        code = symbol.split(".")[0]
        return code in get_latest_hk_connect_codes()

    def get_financial_annual(self, symbol: str):
        """仅取年报口径(REPORT_DATE = -12-31)。
        用于 ROE 等需要年化口径的指标,避免季报累计值。"""
        return self._market_data.get_financial_annual(symbol, date=self.current_date)

    def get_balance(self, symbol: str):
        return self._market_data.get_balance(symbol, date=self.current_date)

    def get_balance_annual(self, symbol: str):
        return self._market_data.get_balance_annual(symbol, date=self.current_date)

    def get_cashflow(self, symbol: str):
        return self._market_data.get_cashflow(symbol, date=self.current_date)

    def get_cashflow_annual(self, symbol: str):
        return self._market_data.get_cashflow_annual(symbol, date=self.current_date)

    def get_financial_annual_history(self, symbol: str, n: int):
        return self._market_data.get_financial_annual_history(
            symbol, date=self.current_date, n=n
        )

    def get_balance_annual_history(self, symbol: str, n: int):
        return self._market_data.get_balance_annual_history(
            symbol, date=self.current_date, n=n
        )

    def get_cashflow_annual_history(self, symbol: str, n: int):
        return self._market_data.get_cashflow_annual_history(
            symbol, date=self.current_date, n=n
        )

    def get_income_annual_history(self, symbol: str, n: int):
        return self._market_data.get_income_annual_history(
            symbol, date=self.current_date, n=n
        )

    def indicator(self, name: str, symbol: str, **kwargs):
        return self._market_data.indicator(name, symbol, idx=self.current_idx, **kwargs)

    def get_indicator(
        self, name: str, symbol: str, period: str = "daily", **kwargs
    ) -> float | None:
        return self._market_data.get_indicator(
            name, symbol, idx=self.current_idx, period=period, **kwargs
        )

    # ===== 决策日志(可选)=====
    # log_sink 为 None 时所有方法静默,保持与旧 ScreenContext 行为兼容
    def _common_log_kwargs(self) -> dict[str, Any]:
        return {
            "idx": self.current_idx,
            "ts": self.current_date,
            "freq": getattr(self.strategy, "frequency", "") if self.strategy else "",
        }

    def log_pass(self, symbol: str, stage: str, **values: Any) -> None:
        if self.log_sink is None:
            return
        self.log_sink.log_pass(symbol, stage, **self._common_log_kwargs(), **values)

    def log_reject(self, symbol: str, stage: str, reason: str, **values: Any) -> None:
        if self.log_sink is None:
            return
        self.log_sink.log_reject(
            symbol, stage, reason=reason, **self._common_log_kwargs(), **values
        )

    def log_flow(self, stage: str, **counts: Any) -> None:
        if self.log_sink is None:
            return
        self.log_sink.log_flow(
            stage, idx=self.current_idx, ts=self.current_date, **counts
        )

    def remove_target(self, symbol: str) -> None:
        pass
