import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import pandas as pd
from services.backtest.base import ScreenerStrategy


class MaTangleBreakoutScreener(ScreenerStrategy):
    name = "月线均线缠绕"
    description = "月线MA5/MA10/MA20在阈值范围内纠缠"
    frequency = "monthly"

    params = {
        "fast": {"default": 5},
        "mid": {"default": 10},
        "slow": {"default": 20},
        "threshold": {"default": 0.05},
        "tangle_months": {"default": 2},
    }

    def screen(self, ctx, symbols):
        result = []
        need_bars = self.p.slow + self.p.tangle_months + 2
        for sym in symbols:
            history = ctx.get_history(sym, need_bars)
            if len(history) < self.p.slow + self.p.tangle_months + 1:
                continue
            df = pd.DataFrame(history)
            col_f = f"ma{self.p.fast}"
            col_m = f"ma{self.p.mid}"
            col_s = f"ma{self.p.slow}"
            for w, col in [(self.p.fast, col_f), (self.p.mid, col_m), (self.p.slow, col_s)]:
                df[col] = df["close"].rolling(window=w, min_periods=w).mean()
            df = df.dropna(subset=[col_f, col_m, col_s]).reset_index(drop=True)
            if len(df) < self.p.tangle_months:
                continue
            tangle_count = 0
            for i in range(len(df) - 1, -1, -1):
                row = df.iloc[i]
                avg = (row[col_f] + row[col_m] + row[col_s]) / 3.0
                if avg == 0:
                    break
                dev_f = abs(row[col_f] - avg) / avg
                dev_m = abs(row[col_m] - avg) / avg
                dev_s = abs(row[col_s] - avg) / avg
                if dev_f <= self.p.threshold and dev_m <= self.p.threshold and dev_s <= self.p.threshold:
                    tangle_count += 1
                else:
                    break
            if tangle_count >= self.p.tangle_months:
                result.append(sym)
        return result
