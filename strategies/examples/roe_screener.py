import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy


class RoeScreener(ScreenerStrategy):
    name = "ROE筛选"
    description = "筛选净资产收益率(ROE)不低于指定值的股票"
    frequency = "daily"

    params = {
        "min_roe": {"default": 10},
    }

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            fin = ctx.get_financial(sym)
            if fin is None:
                continue
            roe = fin.get("净资产收益率")
            if roe is None:
                continue
            if roe >= self.p.min_roe:
                result.append(sym)
        return result
