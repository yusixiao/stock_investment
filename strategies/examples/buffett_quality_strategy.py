"""Buffett 风格质量策略(F 方向)— BuffettQualityStrategy。

完全换思路:不追短期成长,只买**长期高质量 + 估值合理**。

筛选(每年 5/9/11 月初):
1. 连续 3 年年报 ROE ≥ roe_min(默认 15%)— 持续高 ROE 是真护城河
2. peTTM ≤ pe_max(默认 30)— 估值合理,不买在贵价位
3. PB > 0,非 ST,估值时效性 OK

排序:近 3 年平均 ROE 降序,取 top_n,等权 1/N。

理论:
- 持续高 ROE 排除周期股(Q1 高 / 全年低)、伪成长(短期暴增 + 长期均值低)
- PE ≤ 30 是宽松的估值约束(GARP 派 PEG 已被验证不靠谱)
- ROE 平均值排序优于 PEG,避免被分母虚高的伪成长干扰

这是 GARP 失败后的对照实验,验证「质量 + 合理估值」是否优于「成长 + PEG」。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from strategies.base import Strategy
from strategies.utils import growth_long
from strategies.examples.low_valuation_quarterly_strategy import _is_st_on


class BuffettQualityStrategy(Strategy):
    name = "Buffett 质量(3Y ROE + PE 合理)"
    description = (
        "连续 3 年年报 ROE ≥ 15% AND peTTM ≤ 30,按 3 年平均 ROE 降序取前 N 等权。"
        "不追成长,买持续高质量。每年 5/9/11 月调仓。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        "roe_min": {
            "default": 15.0,
            "type": "float",
            "label": "近 3 年每年 ROE 下限(%)",
        },
        "pe_max": {
            "default": 30.0,
            "type": "float",
            "label": "peTTM 上限",
        },
        "roe_years": {
            "default": 3,
            "type": "int",
            "label": "ROE 持续年数",
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
            "default": [5, 9, 11],
            "type": "list[int]",
            "label": "调仓月份",
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

        roe_min = float(self.p.roe_min)
        pe_max = float(self.p.pe_max)
        roe_years = int(self.p.roe_years)
        top_n = int(self.p.top_n)
        staleness_days = int(self.p.max_valuation_staleness_days)

        # ---- Stage 1: 估值健康 + PE 上限 + ST + 时效性 ----
        stage1: list[str] = []
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
            pb = val.get("pbMRQ")
            if pd.isna(pe) or pe is None or pe <= 0 or pe > pe_max:
                continue
            if pd.isna(pb) or pb is None or pb <= 0:
                continue
            if _is_st_on(sym, cur_str):
                continue
            stage1.append(sym)
            ctx.record_factor(sym, "PE", float(pe))
        ctx.log_flow("strategy.pe_filter", passed=len(stage1))

        # ---- Stage 2: 连续 N 年 ROE ≥ 阈值 ----
        stage2: list[tuple[str, float]] = []  # (sym, avg_roe)
        for sym in stage1:
            if not growth_long.all_roe_above(ctx, sym, roe_min, years=roe_years):
                continue
            avg = growth_long.avg_roe(ctx, sym, years=roe_years)
            if avg is None:
                continue
            stage2.append((sym, avg))
            ctx.record_factor(sym, f"AvgROE{roe_years}Y", avg)
        ctx.log_flow("strategy.roe_persistence", passed=len(stage2))

        # ---- Stage 3: 平均 ROE 降序,取 top_n ----
        stage2.sort(key=lambda x: -x[1])
        selected = [sym for sym, _ in stage2[:top_n]]
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
