import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import SellStrategy


class PESell(SellStrategy):
    name = "PE卖出"
    description = "当持仓股票PE超过阈值时清仓卖出"

    params = {
        "pe_threshold": {"default": 40.0},
    }

    def on_bar(self, ctx):
        for sym in list(ctx.get_positions()):
            val = ctx.get_valuation(sym)
            if val is None:
                continue
            pe = val.get("pe")
            if pe is not None and pe > self.p.pe_threshold:
                pos = ctx.get_position(sym)
                if pos:
                    ctx.order_shares(sym, -pos["shares"])
