"""动量+价值+CSI300择时(MomentumValueStrategy)。

完全抛弃财报选股,纯价格 + 估值驱动。文献(Asness/Moskowitz)显示
6-12 月动量在 A 股有显著 alpha。

逻辑(月度调仓):
1. **L1 宏观择时**:CSI300 close ≤ MA200 → 清仓
2. **市值带**:总市值 50-500 亿元(避超大盘 + 流动性)
3. **动量过滤**:过去 126 交易日(~6 月)累计 return ≥ momentum_min(默认 5%),
   排在样本前 momentum_top_pct(默认 30%)
4. **价值排序**:在动量通过的股票中,按 PB 升序取 top_n
5. 等权 1/N

⚠️ 目标 CAGR ≥ 15%,与项目内任何 baseline 解耦。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from strategies.base import Strategy
from strategies.utils import valuation
from strategies.utils.index_timing import csi300_is_bull
from strategies.examples.low_valuation_quarterly_strategy import _is_st_on


class MomentumValueStrategy(Strategy):
    name = "动量+价值+CSI300择时"
    description = (
        "纯价格驱动:CSI300 MA200 择时 + 6月动量前 30% + PB 升序 Top15。"
        "月度调仓,等权。完全不读财报。目标 CAGR≥15%。"
    )
    frequency = "monthly"
    frequency_overridable = False
    strategy_type = "strategy"

    params = {
        "momentum_lookback_days": {
            "default": 126,
            "type": "int",
            "label": "动量回看交易日(126 ≈ 6 月)",
        },
        "momentum_min_pct": {
            "default": 5.0,
            "type": "float",
            "label": "动量最低门槛(%)",
        },
        "momentum_top_pct": {
            "default": 0.30,
            "type": "float",
            "label": "动量分位上限(0.30 = 前 30%)",
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
        "macro_ma_period": {
            "default": 200,
            "type": "int",
            "label": "沪深300 MA 周期",
        },
        "rebalance_months": {
            "default": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            "type": "list[int]",
            "label": "调仓月份(默认每月)",
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
            return []

        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # ---- L1 宏观择时 ----
        ma_p = int(self.p.macro_ma_period)
        if not csi300_is_bull(cur_str, ma_period=ma_p):
            ctx.log_flow("strategy.macro_timing.bear", reason=f"csi300_below_ma{ma_p}")
            self._target_holdings = []
            self._rebalance_pending = True
            return []

        ctx.log_flow("strategy.macro_timing.bull", ma_period=ma_p)

        mv_min = float(self.p.mv_min_yi) * 1e8
        mv_max = float(self.p.mv_max_yi) * 1e8
        lookback = int(self.p.momentum_lookback_days)
        mom_min = float(self.p.momentum_min_pct) / 100.0
        top_pct = float(self.p.momentum_top_pct)
        top_n = int(self.p.top_n)

        # ---- Stage 1: 市值带 + 非 ST + PB 健康 ----
        stage1: list[tuple[str, float]] = []  # (sym, pb)
        for sym in symbols:
            if _is_st_on(sym, cur_str):
                continue
            val = ctx.get_valuation(sym) if hasattr(ctx, "get_valuation") else None
            if val is None:
                continue
            pb = val.get("pbMRQ")
            if pd.isna(pb) or pb is None or pb <= 0:
                continue
            mv = valuation.get_total_mv(ctx, sym)
            if mv is None or mv < mv_min or mv > mv_max:
                continue
            stage1.append((sym, float(pb)))
        ctx.log_flow("strategy.mv_pb_st", passed=len(stage1))

        # ---- Stage 2: 动量(过去 lookback 日累计 return)----
        stage2: list[tuple[str, float, float]] = []  # (sym, pb, momentum)
        for sym, pb in stage1:
            bars = ctx.get_history(sym, n=lookback + 1, period="daily")
            if not bars or len(bars) < lookback + 1:
                continue
            c0 = bars[0].get("close")
            c1 = bars[-1].get("close")
            if c0 is None or c1 is None or c0 <= 0:
                continue
            mom = float(c1) / float(c0) - 1.0
            if mom < mom_min:
                continue
            stage2.append((sym, pb, mom))
        ctx.log_flow("strategy.momentum_min", passed=len(stage2))

        if not stage2:
            self._target_holdings = []
            self._rebalance_pending = True
            return []

        # ---- Stage 3: 取动量前 top_pct ----
        stage2.sort(key=lambda x: -x[2])
        cutoff = max(top_n, int(len(stage2) * top_pct))
        stage3 = stage2[:cutoff]
        ctx.log_flow("strategy.momentum_quantile", passed=len(stage3))

        # ---- Stage 4: PB 升序取 top_n ----
        stage3.sort(key=lambda x: x[1])
        selected = []
        for sym, pb, mom in stage3[:top_n]:
            selected.append(sym)
            ctx.record_factor(sym, "PB", pb)
            ctx.record_factor(sym, "Mom6M", mom)
            ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(selected))

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
