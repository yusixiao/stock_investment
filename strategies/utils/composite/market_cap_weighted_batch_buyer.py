"""市值加权 N 周分批买入器(跨数据源 + 有状态)。

跨源:total_mv 派生自 close × financial.TOTAL_SHARE 决定权重,按 kline 周线 (open+close)/2 成交。
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

    def step(self, ctx, max_holdings: int | None = None) -> None:
        """每个 on_buy 调用一次。

        max_holdings:持仓上限。已持仓 + 计划中(_buy_plans 中未完成的)≥ 上限时,
        新命中股票不再分配新计划(已分配中的继续执行剩余周次)。
        """
        new_symbols = ctx.new_symbols
        current_date = ctx.current_date

        if new_symbols:
            # 计算「占用槽位数」:已持仓 + 仍在分批中的计划 symbol 集合
            current_held = (
                len(ctx.get_positions()) if hasattr(ctx, "get_positions") else 0
            )
            in_progress = len(self._buy_plans)
            slots_used = max(current_held, in_progress)
            if max_holdings is not None and slots_used >= max_holdings:
                filtered: list[str] = []
            elif max_holdings is not None:
                # 还能新建 N 个计划
                quota = max_holdings - slots_used
                filtered = list(new_symbols[:quota])
            else:
                filtered = list(new_symbols)

            if filtered:
                self._create_buy_plans(ctx, filtered, current_date)

        self._execute_weekly_buys(ctx, current_date)

    # ===== 私有:分配计划 =====
    def _create_buy_plans(self, ctx, new_symbols: list[str], current_date: str) -> None:
        stage = "batch_buyer.allocate"
        mv_map: dict[str, float] = {}
        for sym in new_symbols:
            if sym in self._allocated_symbols:
                continue
            # English schema: total_mv = close × TOTAL_SHARE
            # 取自 financial(EastMoney indicator)+ 当日 close
            fin = ctx.get_financial(sym)
            total_share = fin.get("TOTAL_SHARE") if fin else None
            price = ctx.get_price(sym)
            close = price.get("close") if price else None
            if total_share and close:
                mv_map[sym] = float(close) * float(total_share)
            else:
                mv_map[sym] = 1.0  # 无数据时等权

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
