"""GARP-Trend + 沪深300 MA200 大盘择时(C+A+择时方向)。

针对前 7 个成长变体回撤 60-70% 的根本病因:**无指数趋势保护**。
在 GarpTrendStrategy 基础上叠加宏观择时:沪深300 close ≤ MA(N) 时整仓清空,
直至大盘重新站上 MA(N) 才允许建仓。

逻辑:
- 调仓月触发 → 先看 CSI300 是否站上 MA200
  - **熊市(close ≤ MA200)**:screen 返回 [],on_sell 自动清空全部持仓
  - **牛市(close > MA200)**:走原 GARP-Trend 流程
- 非调仓月不动作

预期:大幅压低回撤,代价是错过部分修复反弹。
"""

from __future__ import annotations

from datetime import date

from strategies.examples.garp_trend_strategy import GarpTrendStrategy
from strategies.utils.index_timing import csi300_is_bull


class GarpMacroTimingStrategy(GarpTrendStrategy):
    name = "GARP+趋势保护+沪深300择时(MA200)"
    description = (
        "在 GarpTrendStrategy 基础上加沪深300 MA200 大盘择时:"
        "指数 close ≤ MA200 时整仓清空,站上 MA200 才走原 GARP 选股。"
        "目标:把回撤从 60-70% 压到 30% 以内。"
    )

    params = {
        **GarpTrendStrategy.params,
        "macro_ma_period": {
            "default": 200,
            "type": "int",
            "label": "沪深300 MA 周期(交易日)",
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

        # ---- 宏观择时硬过滤:CSI300 ≤ MA(N) → 清仓 ----
        ma_period = int(self.p.macro_ma_period)
        if not csi300_is_bull(cur_str, ma_period=ma_period):
            ctx.log_flow(
                "strategy.macro_timing.bear",
                reason=f"csi300_below_ma{ma_period}",
            )
            # 设置空目标 → on_sell 会清掉所有持仓,on_buy 不动
            self._target_holdings = []
            self._rebalance_pending = True
            return []

        ctx.log_flow("strategy.macro_timing.bull", ma_period=ma_period)
        return super().screen(ctx, symbols)
