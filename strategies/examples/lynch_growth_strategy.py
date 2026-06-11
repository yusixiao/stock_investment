"""彼得·林奇 (Peter Lynch)「One Up On Wall Street」成长股策略。

参考《彼得·林奇的成功投资》核心 5 条:
1. **连续 2 期净利 YoY ≥ 20%**(Fast Grower 标准,过滤一次性脉冲)
2. **PEG = peTTM / (3Y 净利 CAGR ×100) ≤ 1**(林奇经典估值锚)
3. **流通市值 50-500 亿元**(避超大盘 + 避超小盘流动性陷阱;林奇偏爱
   未被机构充分覆盖的中等市值)
4. **peTTM > 0**(过滤亏损,PE 必须有意义),非 ST
5. **排序 PEG 升序**,Top N 等权,季度调仓(3/6/9/12 月)

⚠️ 本策略不对标项目内任何 baseline,**目标年化 ≥ 15%**。
⚠️ 林奇原书还有「库存增速 < 销售增速」「机构持股 < X%」「热门行业回避」等
   定性规则,本机械版本暂不实现。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from strategies.base import Strategy
from strategies.utils import financial, growth, growth_long, valuation
from strategies.examples.low_valuation_quarterly_strategy import _is_st_on


class LynchGrowthStrategy(Strategy):
    name = "Lynch成长(2YoY+PEG≤1+中市值)"
    description = (
        "彼得·林奇 Fast Grower 机械化:连续 2 期净利 YoY≥20%,PEG≤1,"
        "流通市值 50-500 亿。PEG 升序 Top15 等权,季度调仓。目标 CAGR≥15%。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        "yoy_min": {
            "default": 20.0,
            "type": "float",
            "label": "净利 YoY 下限(%,需连续 2 期满足)",
        },
        "peg_max": {
            "default": 1.0,
            "type": "float",
            "label": "PEG 上限(林奇经典锚)",
        },
        "cagr_min": {
            "default": 0.15,
            "type": "float",
            "label": "3 年净利 CAGR 下限(用于 PEG 分母)",
        },
        "mv_min_yi": {
            "default": 50.0,
            "type": "float",
            "label": "总市值下限(亿元)",
        },
        "mv_max_yi": {
            "default": 500.0,
            "type": "float",
            "label": "总市值上限(亿元)",
        },
        "top_n": {
            "default": 15,
            "type": "int",
            "label": "持仓数量",
        },
        "max_valuation_staleness_days": {
            "default": 5,
            "type": "int",
            "label": "估值数据时效上限(交易日)",
        },
        "rebalance_months": {
            "default": [3, 6, 9, 12],
            "type": "list[int]",
            "label": "调仓月份(季度调仓)",
        },
    }

    def __init__(self, param_overrides: dict | None = None):
        super().__init__(param_overrides)
        self._target_holdings: list[str] = []
        self._rebalance_pending: bool = False

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        cur_str = ctx.current_date
        if not cur_str:
            return []
        try:
            cur_d = date.fromisoformat(cur_str[:10])
        except (ValueError, TypeError):
            return []

        rebal_months = self.p.rebalance_months
        if isinstance(rebal_months, str):
            rebal_months = [int(x) for x in rebal_months.split(",") if x.strip()]
        if cur_d.month not in set(rebal_months):
            ctx.log_flow("strategy.screen.skip", reason="not_rebalance_month")
            return []

        ctx.log_flow("strategy.screen.start", input=len(symbols))

        yoy_min = float(self.p.yoy_min)
        peg_max = float(self.p.peg_max)
        cagr_min = float(self.p.cagr_min)
        mv_min = float(self.p.mv_min_yi) * 1e8  # 亿 → 元
        mv_max = float(self.p.mv_max_yi) * 1e8
        top_n = int(self.p.top_n)
        staleness_days = int(self.p.max_valuation_staleness_days)

        # ---- Stage 1: PE 健康 + 非 ST + 时效性 + 市值带 ----
        stage1: list[tuple[str, float]] = []  # (sym, pe)
        for sym in symbols:
            val = ctx.get_valuation(sym) if hasattr(ctx, "get_valuation") else None
            if val is None:
                continue
            val_date = val.get("date")
            if val_date is not None:
                try:
                    vd = date.fromisoformat(str(val_date)[:10])
                    if (cur_d - vd).days > staleness_days * 2:
                        continue
                except (ValueError, TypeError):
                    pass
            pe = val.get("peTTM")
            if pd.isna(pe) or pe is None or pe <= 0:
                continue
            if _is_st_on(sym, cur_str):
                continue
            mv = valuation.get_total_mv(ctx, sym)
            if mv is None or mv < mv_min or mv > mv_max:
                continue
            stage1.append((sym, float(pe)))
        ctx.log_flow("strategy.pe_st_mv", passed=len(stage1))

        # ---- Stage 2: 连续 2 期净利 YoY ≥ yoy_min(用 PARENTNETPROFITTZ)----
        stage2: list[tuple[str, float]] = []  # (sym, pe)
        for sym, pe in stage1:
            yoys = growth_long.get_recent_net_profit_yoy(ctx, sym, n=2)
            if yoys is None or len(yoys) < 2:
                continue
            if any(y is None or y < yoy_min for y in yoys):
                continue
            stage2.append((sym, pe))
            ctx.record_factor(sym, "YoY_T0", yoys[0])
            ctx.record_factor(sym, "YoY_T1", yoys[1])
        ctx.log_flow("strategy.yoy_2y", passed=len(stage2))

        # ---- Stage 3: 3Y CAGR 计算 PEG,过滤 PEG ≤ peg_max ----
        stage3: list[tuple[str, float]] = []  # (sym, peg)
        for sym, pe in stage2:
            cagr = growth_long.get_net_profit_cagr(ctx, sym, years=3)
            if cagr is None or cagr < cagr_min:
                continue
            # PEG = PE / (CAGR%) ;CAGR 0.20 → 20
            cagr_pct = cagr * 100.0
            if cagr_pct <= 0:
                continue
            peg = pe / cagr_pct
            if peg > peg_max or peg <= 0:
                continue
            stage3.append((sym, peg))
            ctx.record_factor(sym, "PE", pe)
            ctx.record_factor(sym, "CAGR3Y", cagr)
            ctx.record_factor(sym, "PEG", peg)
        ctx.log_flow("strategy.peg", passed=len(stage3))

        # ---- Stage 4: PEG 升序,取 top_n ----
        stage3.sort(key=lambda x: x[1])
        selected = [sym for sym, _ in stage3[:top_n]]
        for sym in selected:
            ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow(
            "strategy.screen.done",
            input=len(symbols),
            passed=len(selected),
        )

        self._target_holdings = selected
        self._rebalance_pending = True
        return selected

    def on_sell(self, ctx) -> None:
        if not self._rebalance_pending:
            return
        target_set = set(self._target_holdings)
        positions = list(ctx.get_positions().items())
        for sym, pos in positions:
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            if shares <= 0:
                continue
            if sym in target_set:
                continue
            ctx.order_shares(sym, -int(shares))
            try:
                ctx.target_symbols.discard(sym)
            except AttributeError:
                pass

    def on_buy(self, ctx) -> None:
        if not self._rebalance_pending:
            return
        target = self._target_holdings
        if not target:
            self._rebalance_pending = False
            return
        target_pct = 1.0 / float(len(target))
        for sym in target:
            ctx.order_target_percent(sym, target_pct)
        self._rebalance_pending = False
