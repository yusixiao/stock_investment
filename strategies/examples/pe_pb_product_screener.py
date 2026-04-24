import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy


class PePbProductScreener(ScreenerStrategy):
    name = "PE*PB乘积筛选"
    description = "筛选PE(TTM)*PB乘积在指定范围内的股票"
    frequency = "daily"

    params = {
        "min_value": {"default": 0.0},
        "max_value": {"default": 22.0},
    }

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            val = ctx.get_valuation(sym)
            if val is None:
                continue
            pe = val.get("pe_ttm")
            pb = val.get("pb")
            if pe is None or pb is None:
                continue
            product = pe * pb
            if self.p.min_value <= product <= self.p.max_value:
                result.append(sym)
        return result
