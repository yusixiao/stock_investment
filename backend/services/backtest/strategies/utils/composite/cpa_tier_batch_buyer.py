"""CPA tier-based 分批买入器(对齐 CPA 原文 100%/70% 仓位口径)。

设计动机(2026-05-28):
    `MarketCapWeightedBatchBuyer` 在命中股之间按市值加权分钱,与 CPA 原文
    "单股按 tier% 配置仓位" 的语义不一致。本 buyer 改为:

    单股目标仓位 = max_per_stock_pct × TIER_PCT[tier]
        full     → max_per_stock_pct × 100%
        p70      → max_per_stock_pct × 70%
        observe  → 不分配(只观察)
        skip     → 不分配

    分 N 周(buy_weeks)等额爬坡到目标仓:
        每周目标仓 = target_pct × (week_idx / buy_weeks)
        通过 ctx.order_target_percent(sym, weekly_target) 下单

    资金超额由 broker 在 T+1 撮合时按现金可用度拒接(不做前置精确计算)。

参数:
    max_per_stock_pct(默认 0.20):单股仓位绝对上限,full=20%
    buy_weeks(默认 4):分批周数
    tier_pct_map:可覆盖 TIER_PCT(默认从 services.backtest.strategies.utils.conservative 导入)

使用:
    self._buyer = CpaTierBatchBuyer(max_per_stock_pct=0.20, buy_weeks=4)
    在 on_buy 调 self._buyer.step(ctx, max_holdings=...)
"""

from __future__ import annotations

from datetime import date as _date

from services.backtest.strategies.utils.conservative import TIER_PCT as _DEFAULT_TIER_PCT


class CpaTierBatchBuyer:
    def __init__(
        self,
        *,
        max_per_stock_pct: float = 0.20,
        buy_weeks: int = 4,
        tier_pct_map: dict[str, float] | None = None,
    ):
        self._max_per_stock_pct = max_per_stock_pct
        self._buy_weeks = buy_weeks
        self._tier_pct_map = (
            dict(tier_pct_map) if tier_pct_map is not None else dict(_DEFAULT_TIER_PCT)
        )
        # {symbol: {"target_pct": float, "weeks_bought": int,
        #            "start_week_key": str, "last_buy_week_key": str|None,
        #            "tier": str}}
        self._buy_plans: dict[str, dict] = {}
        self._allocated_symbols: set[str] = set()

    def step(self, ctx, max_holdings: int | None = None) -> None:
        """每个 on_buy 调用一次。

        max_holdings:持仓上限。已持仓 + 计划中(_buy_plans 中未完成)≥ 上限时,
        新命中股票不再分配(已分配的继续执行剩余周次)。
        """
        new_symbols = ctx.new_symbols
        current_date = ctx.current_date

        if new_symbols:
            current_held = (
                len(ctx.get_positions()) if hasattr(ctx, "get_positions") else 0
            )
            in_progress = len(self._buy_plans)
            slots_used = max(current_held, in_progress)
            if max_holdings is not None and slots_used >= max_holdings:
                filtered: list[str] = []
            elif max_holdings is not None:
                quota = max_holdings - slots_used
                filtered = list(new_symbols[:quota])
            else:
                filtered = list(new_symbols)

            if filtered:
                self._create_buy_plans(ctx, filtered, current_date)

        self._execute_weekly_buys(ctx, current_date)

    # ===== 私有:分配计划 =====
    def _create_buy_plans(self, ctx, new_symbols: list[str], current_date: str) -> None:
        stage = "cpa_tier_buyer.allocate"
        week_key = self._week_key(current_date)

        for sym in new_symbols:
            if sym in self._allocated_symbols:
                continue
            factors = (
                ctx.get_factors(sym) if hasattr(ctx, "get_factors") else {}
            ) or {}
            tier = factors.get("position_tier")
            tier_ratio = self._tier_pct_map.get(tier, 0.0) if tier else 0.0
            if tier_ratio <= 0:
                # observe / skip / 未知 tier → 不分配
                ctx.log_reject(
                    sym, stage, "tier_no_allocation", tier=tier, tier_ratio=tier_ratio
                )
                continue
            target_pct = self._max_per_stock_pct * tier_ratio
            self._buy_plans[sym] = {
                "target_pct": target_pct,
                "weeks_bought": 0,
                "start_week_key": week_key,
                "last_buy_week_key": None,
                "tier": tier,
            }
            self._allocated_symbols.add(sym)
            ctx.log_pass(
                sym,
                stage,
                tier=tier,
                tier_ratio=tier_ratio,
                target_pct=target_pct,
                buy_weeks=self._buy_weeks,
            )

    # ===== 私有:执行买入 =====
    def _execute_weekly_buys(self, ctx, current_date: str) -> None:
        stage = "cpa_tier_buyer.buy"
        current_week = self._week_key(current_date)

        # 按 target_pct 降序,full 优先(更想要的先吃现金)
        sorted_plans = sorted(
            self._buy_plans.items(),
            key=lambda x: x[1].get("target_pct", 0),
            reverse=True,
        )

        finished: list[str] = []
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

            # 本周递增到的目标仓位 = target_pct × (week_idx+1) / buy_weeks
            week_idx = plan["weeks_bought"] + 1
            weekly_target_pct = plan["target_pct"] * week_idx / self._buy_weeks

            # order_target_percent:让持仓达到 weekly_target_pct(broker 自动按现金可用度处理)
            ctx.order_target_percent(sym, weekly_target_pct)
            plan["weeks_bought"] = week_idx
            plan["last_buy_week_key"] = current_week
            ctx.log_pass(
                sym,
                stage,
                week=current_week,
                week_index=week_idx,
                total_weeks=self._buy_weeks,
                weekly_target_pct=weekly_target_pct,
                final_target_pct=plan["target_pct"],
                tier=plan["tier"],
            )

        for sym in finished:
            del self._buy_plans[sym]

    # ===== 私有:辅助 =====
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
