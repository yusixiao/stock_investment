import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import TraderStrategy


class EqualWeightTrader(TraderStrategy):
    name = "等权买入持有"
    description = "对筛选出的股票等权分配资金买入，定期调仓"

    params = {
        "rebalance_days": {"default": 20},
    }

    settings = {
        "initial_capital": 1_000_000,
        "commission_rate": 0.0003,
        "slippage": 0.002,
    }

    def on_bar(self, ctx):
        if ctx.days_since_rebalance >= self.p.rebalance_days:
            targets = ctx.selected_symbols
            target_pct = 1.0 / max(len(targets), 1)
            for sym in ctx.get_positions():
                if sym not in targets:
                    ctx.order_target_percent(sym, 0.0)
            for sym in targets:
                ctx.order_target_percent(sym, target_pct)
            ctx.reset_rebalance_counter()
