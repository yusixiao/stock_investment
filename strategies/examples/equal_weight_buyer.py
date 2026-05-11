import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import BuyStrategy


class EqualWeightBuyer(BuyStrategy):
    name = "等权买入"
    description = "对选中股票等权分配资金买入"

    params = {
        "max_positions": {"default": 10},
    }

    def on_bar(self, ctx):
        targets = ctx.selected_symbols[:self.p.max_positions]
        if not targets:
            return
        portfolio = ctx.get_portfolio()
        per_stock = portfolio["total_value"] / self.p.max_positions
        for sym in targets:
            if ctx.get_position(sym) is None:
                ctx.order_value(sym, per_stock)
