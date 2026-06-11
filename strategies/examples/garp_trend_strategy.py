"""GARP + 趋势保护(C+A 方向)— GarpTrendStrategy。

针对 GARP v1 在 A 股惨败的两个核心病因:
1. 1 年 YOY 噪声大 + 易抓低基数伪成长 → 改用 **3 年净利 CAGR**
2. 60% 回撤无趋势保护 → **月线 close > MA12** 硬过滤(跌破即不持有)

筛选(每年 5/9/11 月初):
1. 3 年净利 CAGR ≥ profit_cagr_min(默认 15%)
2. ROE(年报)≥ roe_min(默认 12%)
3. 净现比 ≥ ocf_to_np_min(默认 0.7)
4. 月线 close > MA12(13 月均线,趋势硬过滤)
5. peTTM > 0,PB > 0,非 ST,估值时效性 OK

排序:3 年 CAGR 降序,取 top_n,等权 1/N。

⚠️ 月线 MA12 注意:用 ctx.get_history(period='monthly', n=13) 拉 13 根月线,
   计算前 12 根均价作为 MA12,要求当月 close > MA12。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from strategies.base import Strategy
from strategies.utils import financial, growth_long
from strategies.examples.low_valuation_quarterly_strategy import _is_st_on


class GarpTrendStrategy(Strategy):
    name = "GARP+趋势保护(3Y CAGR + MA12)"
    description = (
        "针对 GARP 在 A 股的两个病因:1) 1Y YOY → 3Y 净利 CAGR(过滤伪成长);"
        "2) 加月线 MA12 趋势硬过滤(跌破不持有,降回撤)。"
        "默认:3Y CAGR≥15%、ROE≥12%、净现比≥0.7,Top15 等权,5/9/11 月调仓。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        "profit_cagr_min": {
            "default": 0.15,
            "type": "float",
            "label": "3 年净利 CAGR 下限(小数,如 0.15=15%)",
        },
        "roe_min": {
            "default": 12.0,
            "type": "float",
            "label": "ROE 下限(%,年报口径)",
        },
        "ocf_to_np_min": {
            "default": 0.7,
            "type": "float",
            "label": "净现比下限(经营现金流/净利润)",
        },
        "use_ma12_trend": {
            "default": True,
            "type": "bool",
            "label": "启用月线 MA12 趋势过滤",
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

        cagr_min = float(self.p.profit_cagr_min)
        roe_min = float(self.p.roe_min)
        ocf_min = float(self.p.ocf_to_np_min)
        use_ma12 = bool(self.p.use_ma12_trend)
        top_n = int(self.p.top_n)
        staleness_days = int(self.p.max_valuation_staleness_days)

        # ---- Stage 1: 估值健康 + ST + 时效性 ----
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
            if pd.isna(pe) or pe is None or pe <= 0:
                continue
            if pd.isna(pb) or pb is None or pb <= 0:
                continue
            if _is_st_on(sym, cur_str):
                continue
            stage1.append(sym)
        ctx.log_flow("strategy.valuation_st", passed=len(stage1))

        # ---- Stage 2: 3 年净利 CAGR + ROE + 净现比 ----
        from strategies.utils import growth as growth_short

        stage2: list[tuple[str, float]] = []  # (sym, cagr)
        for sym in stage1:
            cagr = growth_long.get_net_profit_cagr(ctx, sym, years=3)
            if cagr is None or cagr < cagr_min:
                continue
            roe = financial.get_roe_annual_as_of_notice(ctx, sym)
            if roe is None or roe < roe_min:
                continue
            metrics = growth_short.get_growth_metrics_as_of_notice(ctx, sym)
            if metrics is None:
                continue
            ocf_np = metrics.get("NCO_NETPROFIT")
            if ocf_np is None or ocf_np < ocf_min:
                continue
            stage2.append((sym, cagr))
            ctx.record_factor(sym, "ProfitCAGR3Y", cagr)
            ctx.record_factor(sym, "ROE", roe)
            ctx.record_factor(sym, "OCF/NP", ocf_np)
        ctx.log_flow("strategy.cagr_quality", passed=len(stage2))

        # ---- Stage 3: 月线 MA12 趋势过滤(可选)----
        if use_ma12 and stage2:
            stage3: list[tuple[str, float]] = []
            for sym, cagr in stage2:
                bars = ctx.get_history(sym, n=13, period="monthly")
                if not bars or len(bars) < 13:
                    continue
                # 用前 12 根月线均价作 MA12
                ma12 = float(np.mean([b.get("close", 0) for b in bars[:12]]))
                last_close = bars[-1].get("close")
                if last_close is None or ma12 <= 0:
                    continue
                if float(last_close) <= ma12:
                    continue
                stage3.append((sym, cagr))
                ctx.record_factor(sym, "Close/MA12", float(last_close) / ma12)
            ctx.log_flow("strategy.ma12_trend", passed=len(stage3))
        else:
            stage3 = stage2

        # ---- Stage 4: CAGR 降序,取 top_n ----
        stage3.sort(key=lambda x: -x[1])
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
