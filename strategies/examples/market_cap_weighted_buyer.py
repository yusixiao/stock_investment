"""按市值加权、8周定投买入策略。

规则：
- 同月内新增的股票按总市值比例分配初始资金
- 每只股票从匹配日起8周内分次买入，每周买入分配金额的1/8
- 买入价格为该周K线的 (open + close) / 2
- 现金不足时按实际可用金额买入，需满足最少100股
- 后续可替换总市值为流通市值
"""

from services.backtest.base import BuyStrategy


class MarketCapWeightedBuyer(BuyStrategy):
    name = "市值加权定投买入"
    description = "按总市值比例分配资金，8周定投买入"
    strategy_type = "buy"
    params = {
        "buy_weeks": {"default": 8, "label": "买入周数", "type": "int"},
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        # 买入计划: {symbol: {"weekly_amount": float, "start_date": str, "weeks_bought": int, "market_cap": float}}
        self._buy_plans: dict[str, dict] = {}
        # 记录已处理过的股票，避免重复分配
        self._allocated_symbols: set[str] = set()

    def on_bar(self, ctx):

        current_date = ctx._current_date
        new_symbols = ctx.new_symbols

        # 为新增股票创建买入计划（按市值比例分配）
        if new_symbols:
            self._create_buy_plans(ctx, new_symbols, current_date)

        # 执行本周的买入（判断是否进入新的一周）
        self._execute_weekly_buys(ctx, current_date)

    def _create_buy_plans(self, ctx, new_symbols: list[str], current_date: str):
        """为新增股票按市值比例分配当前可用资金并创建买入计划。"""
        # 获取各股票总市值
        mv_map = {}
        for sym in new_symbols:
            if sym in self._allocated_symbols:
                continue
            val = ctx.get_valuation(sym)
            if val and val.get("total_mv"):
                mv_map[sym] = val["total_mv"]
            else:
                # 无市值数据时用默认值1，等权分配
                mv_map[sym] = 1.0

        if not mv_map:
            return

        total_mv = sum(mv_map.values())
        buy_weeks = self.p.buy_weeks
        available = ctx.available_cash

        for sym, mv in mv_map.items():
            ratio = mv / total_mv
            allocated_amount = available * ratio
            weekly_amount = allocated_amount / buy_weeks

            self._buy_plans[sym] = {
                "weekly_amount": weekly_amount,
                "start_date": current_date,
                "weeks_bought": 0,
                "start_week_key": self._week_key(current_date),
                "last_buy_week_key": None,
                "market_cap": mv,
            }
            self._allocated_symbols.add(sym)

    def _execute_weekly_buys(self, ctx, current_date: str):
        """检查每只股票是否需要在本周买入，按总市值从大到小排序优先买入。"""
        current_week = self._week_key(current_date)
        buy_weeks = self.p.buy_weeks

        # 按市值降序排列，资金不足时优先保证大市值股票成交
        sorted_plans = sorted(
            self._buy_plans.items(),
            key=lambda x: x[1].get("market_cap", 0),
            reverse=True,
        )

        finished = []
        pending_cost = 0.0
        for sym, plan in sorted_plans:
            if plan["weeks_bought"] >= buy_weeks:
                finished.append(sym)
                continue

            # 每周只买一次
            if plan["last_buy_week_key"] == current_week:
                continue

            # 计算从起始周到当前周经过了几周
            weeks_elapsed = self._weeks_between(plan["start_week_key"], current_week)
            if weeks_elapsed < 0:
                continue

            # 确认该股票还在 target_symbols 中（未被 seller 移除）
            if sym not in ctx.target_symbols:
                finished.append(sym)
                continue

            # 用周线 (open + close) / 2 作为买入价
            price = self._get_weekly_mid_price(ctx, sym)
            if price is None or price <= 0:
                continue

            # 扣除本轮已预留的资金，避免同一bar内多笔下单超额
            target_amount = plan["weekly_amount"]
            available = ctx.available_cash - pending_cost
            actual_amount = min(target_amount, available)

            shares = int(actual_amount / price)
            # 取整到100股（整手）
            shares = (shares // 100) * 100

            if shares >= 100:
                ctx.order_shares(sym, shares)
                pending_cost += shares * price
                plan["weeks_bought"] += 1
                plan["last_buy_week_key"] = current_week

        for sym in finished:
            del self._buy_plans[sym]

    def _get_weekly_mid_price(self, ctx, symbol: str) -> float | None:
        """获取当前周的 (open + close) / 2 价格。"""
        price_data = ctx.get_price(symbol, period="weekly")
        if price_data is None:
            # 回退到日线价格
            price_data = ctx.get_price(symbol)
        if price_data is None:
            return None
        return (price_data["open"] + price_data["close"]) / 2

    def _week_key(self, date_str: str) -> str:
        """生成周键（ISO周）。"""
        from datetime import date as _date
        dt = _date.fromisoformat(date_str)
        yr, wk, _ = dt.isocalendar()
        return f"{yr}-W{wk:02d}"

    def _weeks_between(self, start_week: str, current_week: str) -> int:
        """计算两个周键之间的周数差。"""
        from datetime import date as _date, timedelta
        # 将周键转为该周的周一日期
        s_year, s_week = int(start_week[:4]), int(start_week.split("W")[1])
        c_year, c_week = int(current_week[:4]), int(current_week.split("W")[1])
        s_date = _date.fromisocalendar(s_year, s_week, 1)
        c_date = _date.fromisocalendar(c_year, c_week, 1)
        return (c_date - s_date).days // 7
