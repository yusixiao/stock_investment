import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy


class MaCrossScreener(ScreenerStrategy):
    name = "MA金叉选股"
    description = "选出短期MA上穿长期MA的股票"

    params = {
        "fast": {"default": 5},
        "slow": {"default": 20},
        "period": {"default": "monthly"},
    }

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            ma_f = ctx.indicator(sym, "ma", self.p.fast, period=self.p.period)
            ma_s = ctx.indicator(sym, "ma", self.p.slow, period=self.p.period)
            if ma_f is not None and ma_s is not None and ma_f > ma_s:
                result.append(sym)
        return result
