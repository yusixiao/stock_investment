import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import pandas as pd
from services.backtest.base import ScreenerStrategy
from services.indicator import calc_macd


class MonthlyMacdPositiveScreener(ScreenerStrategy):
    name = "月线MACD连续为正"
    description = "月线MACD柱连续N个月为正值"
    frequency = "monthly"

    params = {
        "consecutive_months": {"default": 4},
    }

    def screen(self, ctx, symbols):
        result = []
        need_bars = 35 + self.p.consecutive_months
        for sym in symbols:
            history = ctx.get_history(sym, need_bars)
            if len(history) < 27 + self.p.consecutive_months:
                continue
            df = pd.DataFrame(history)
            macd_df = calc_macd(df)
            macd_vals = macd_df["macd"].tolist()
            if len(macd_vals) < self.p.consecutive_months:
                continue
            tail = macd_vals[-self.p.consecutive_months:]
            if all(v is not None and v > 0 for v in tail):
                result.append(sym)
        return result
