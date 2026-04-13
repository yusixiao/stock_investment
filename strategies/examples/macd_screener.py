import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy


class MacdScreener(ScreenerStrategy):
    name = "MACD强势选股"
    description = "选出DIF大于DEA的股票"

    params = {}

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            dif = ctx.indicator(sym, "macd", "dif")
            dea = ctx.indicator(sym, "macd", "dea")
            if dif is not None and dea is not None and dif > dea:
                result.append(sym)
        return result
