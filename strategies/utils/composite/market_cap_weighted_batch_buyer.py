"""市值加权 N 周分批买入器(跨数据源 + 有状态)。

跨源:取 valuation.total_mv 决定权重,按 kline 周线 (open+close)/2 成交。
有状态:_buy_plans / _allocated_symbols 跨 step 调用累积,因此封装为 class。

迁移自 strategies/examples/market_cap_weighted_buyer.py(2026-05-18 重构):
- 不再继承 BuyStrategy,改为独立 class
- 公开方法 step(ctx),由 Strategy.on_buy 调用
- 命名 MarketCapWeightedBuyer → MarketCapWeightedBatchBuyer
"""

from datetime import date as _date


class MarketCapWeightedBatchBuyer:
    def __init__(self, *, buy_weeks: int = 8, lot_size: int = 100):
        self._buy_weeks = buy_weeks
        self._lot_size = lot_size
        # {symbol: {"weekly_amount": float, "weeks_bought": int,
        #            "start_week_key": str, "last_buy_week_key": str|None,
        #            "market_cap": float}}
        self._buy_plans: dict[str, dict] = {}
        self._allocated_symbols: set[str] = set()

    def step(self, ctx) -> None:
        """每个 on_buy 调用一次。"""
        new_symbols = ctx.new_symbols
        current_date = ctx.current_date

        if new_symbols:
            self._create_buy_plans(ctx, new_symbols, current_date)

        self._execute_weekly_buys(ctx, current_date)

    # ===== 私有:分配计划 =====
    def _create_buy_plans(self, ctx, new_symbols: list[str], current_date: str) -> None:
        stage = "batch_buyer.allocate"
        mv_map: dict[str, float] = {}
        for sym in new_symbols:
            if sym in self._allocated_symbols:
                continue
            val = ctx.get_valuation(sym)
            if val and val.get("total_mv"):
                mv_map[sym] = val["total_mv"]
            else:
                mv_map[sym] = 1.0  # 无市值数据时等权

        if not mv_map:
            return

        total_mv = sum(mv_map.values())
        available = ctx.available_cash
        week_key = self._week_key(current_date)

        for sym, mv in mv_map.items():
            ratio = mv / total_mv
            allocated_amount = available * ratio
            weekly_amount = allocated_amount / self._buy_weeks
            self._buy_plans[sym] = {
                "weekly_amount": weekly_amount,
                "weeks_bought": 0,
                "start_week_key": week_key,
                "last_buy_week_key": None,
                "market_cap": mv,
            }
            self._allocated_symbols.add(sym)
            ctx.log_pass(
                sym,
                stage,
                mv=mv,
                weight=ratio,
                weekly_amount=weekly_amount,
                buy_weeks=self._buy_weeks,
            )

    # ===== 私有:执行买入 =====
    def _execute_weekly_buys(self, ctx, current_date: str) -> None:
        stage = "batch_buyer.buy"
        current_week = self._week_key(current_date)

        # 按市值降序,资金不足时优先大市值
        sorted_plans = sorted(
            self._buy_plans.items(),
            key=lambda x: x[1].get("market_cap", 0),
            reverse=True,
        )

        finished: list[str] = []
        pending_cost = 0.0

        for sym, plan in sorted_plans:
            if plan["weeks_bought"] >= self._buy_weeks:
                finished.append(sym)
                continue
            if plan["last_buy_week_key"] == current_week:
                continue
            if self._weeks_between(plan["start_week_key"], current_week) < 0:
                continue
            if sym not in ctx.target_symbols:
                # seller 已平仓,移出计划
                finished.append(sym)
                continue

            price = self._get_weekly_mid_price(ctx, sym)
            if price is None or price <= 0:
                continue

            target_amount = plan["weekly_amount"]
            available = ctx.available_cash - pending_cost
            actual_amount = min(target_amount, available)
            shares = (int(actual_amount / price) // self._lot_size) * self._lot_size

            if shares >= self._lot_size:
                ctx.order_shares(sym, shares)
                pending_cost += shares * price
                plan["weeks_bought"] += 1
                plan["last_buy_week_key"] = current_week
                ctx.log_pass(
                    sym,
                    stage,
                    week=current_week,
                    week_index=plan["weeks_bought"],
                    total_weeks=self._buy_weeks,
                    shares=shares,
                    price=price,
                )

        for sym in finished:
            del self._buy_plans[sym]

    # ===== 私有:辅助 =====
    @staticmethod
    def _get_weekly_mid_price(ctx, symbol: str) -> float | None:
        price_data = ctx.get_price(symbol, period="weekly")
        if price_data is None:
            price_data = ctx.get_price(symbol)  # fallback to daily
        if price_data is None:
            return None
        return (price_data["open"] + price_data["close"]) / 2

    @staticmethod
    def _week_key(date_str: str) -> str:
        dt = _date.fromisoformat(date_str)
        yr, wk, _ = dt.isocalendar()
        return f"{yr}-W{wk:02d}"

    @staticmethod
    def _weeks_between(start_week: str, current_week: str) -> int:
        s_year, s_week = int(start_week[:4]), int(start_week.split("W")[1])
        c_year, c_week = int(current_week[:4]), int(current_week.split("W")[1])
        s_d = _date.fromisocalendar(s_year, s_week, 1)
        c_d = _date.fromisocalendar(c_year, c_week, 1)
        return (c_d - s_d).days // 7
