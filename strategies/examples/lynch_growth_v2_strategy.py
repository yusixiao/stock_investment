"""Lynch v2 = Lynch v1 + 沪深300 MA200 大盘择时 + 个股月线 MA12 趋势过滤。

针对 v1 -60.8% / maxDD 85.8% 的两个核心病因:
1. **无大盘择时**:2018/2022/2024 年中熊市直接被打到地板
2. **无个股趋势保护**:基本面满足 PEG≤1 的股票照样可以一路阴跌

加两层防御(顺序执行,任一不通过即剔除):
- **L1 宏观择时**:CSI300 close ≤ MA200 → screen 返 [],清空全部持仓
- **L2 个股趋势**:月线 close > MA12(13 月均线)硬过滤
- **L3 基本面 + PEG**:沿用 v1(2YoY≥20% + PEG≤1 + 50-500亿市值)

⚠️ 目标 CAGR ≥ 15%,对标林奇 Fast Grower。本策略**不与项目内 baseline 比较**。
"""

from __future__ import annotations

from datetime import date

import numpy as np

from strategies.examples.lynch_growth_strategy import LynchGrowthStrategy
from strategies.utils.index_timing import csi300_is_bull


class LynchGrowthV2Strategy(LynchGrowthStrategy):
    name = "Lynch v2(2YoY+PEG≤1+CSI300择时+MA12)"
    description = (
        "Lynch v1 + 双重趋势保护:"
        "L1 沪深300 MA200 熊市清仓;L2 个股月线 close>MA12 硬过滤;L3 沿用 v1 选股。"
        "目标 CAGR≥15%(不与 baseline 对比)。"
    )

    params = {
        **LynchGrowthStrategy.params,
        "macro_ma_period": {
            "default": 200,
            "type": "int",
            "label": "沪深300 MA 周期(交易日)",
        },
        "use_ma12_trend": {
            "default": True,
            "type": "bool",
            "label": "启用个股月线 MA12 趋势过滤",
        },
    }

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

        # ---- L1 宏观择时:CSI300 ≤ MA(N) → 清仓 ----
        ma_period = int(self.p.macro_ma_period)
        if not csi300_is_bull(cur_str, ma_period=ma_period):
            ctx.log_flow(
                "strategy.macro_timing.bear",
                reason=f"csi300_below_ma{ma_period}",
            )
            self._target_holdings = []
            self._rebalance_pending = True
            return []

        ctx.log_flow("strategy.macro_timing.bull", ma_period=ma_period)

        # ---- L3 走原 Lynch 选股(PE+ST+市值+PEG) ----
        selected = super().screen(ctx, symbols)

        # ---- L2 个股月线 MA12 趋势过滤(对 selected 再筛一道)----
        if not bool(self.p.use_ma12_trend) or not selected:
            return selected

        kept: list[str] = []
        for sym in selected:
            bars = ctx.get_history(sym, n=13, period="monthly")
            if not bars or len(bars) < 13:
                continue
            ma12 = float(np.mean([b.get("close", 0) for b in bars[:12]]))
            last_close = bars[-1].get("close")
            if last_close is None or ma12 <= 0:
                continue
            if float(last_close) <= ma12:
                continue
            kept.append(sym)
            ctx.record_factor(sym, "Close/MA12", float(last_close) / ma12)

        ctx.log_flow("strategy.ma12_trend", input=len(selected), passed=len(kept))

        self._target_holdings = kept
        self._rebalance_pending = True
        return kept
