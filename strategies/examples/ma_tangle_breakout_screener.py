import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import pandas as pd
from services.backtest.base import ScreenerStrategy


def _monthly_ma(daily_records, windows):
    if len(daily_records) < 2:
        return pd.DataFrame()
    df = pd.DataFrame(daily_records).sort_values("date").reset_index(drop=True)
    df["date_dt"] = pd.to_datetime(df["date"])
    df["period_key"] = df["date_dt"].dt.to_period("M")
    grouped = df.groupby("period_key", sort=True)
    monthly = pd.DataFrame({
        "date": grouped["date"].last(),
        "close": grouped["close"].last(),
    }).reset_index(drop=True)
    for w in windows:
        monthly[f"ma{w}"] = monthly["close"].rolling(window=w, min_periods=w).mean()
    return monthly


class MaTangleBreakoutScreener(ScreenerStrategy):
    name = "月线均线缠绕突破"
    description = "月线MA5/MA10/MA20纠缠后，MA20向下穿透MA5和MA10（多头突破信号）"

    params = {
        "fast": {"default": 5},
        "mid": {"default": 10},
        "slow": {"default": 20},
        "threshold": {"default": 0.05},
        "tangle_months": {"default": 2},
    }

    def screen(self, ctx, symbols):
        result = []
        lookback = (self.p.slow + self.p.tangle_months + 2) * 30
        for sym in symbols:
            history = ctx.get_history(sym, lookback)
            if len(history) < 2:
                continue
            monthly = _monthly_ma(history, [self.p.fast, self.p.mid, self.p.slow])
            if len(monthly) < self.p.slow + self.p.tangle_months + 1:
                continue
            col_f = f"ma{self.p.fast}"
            col_m = f"ma{self.p.mid}"
            col_s = f"ma{self.p.slow}"
            monthly = monthly.dropna(subset=[col_f, col_m, col_s]).reset_index(drop=True)
            if len(monthly) < self.p.tangle_months + 1:
                continue
            cur = monthly.iloc[-1]
            prev = monthly.iloc[-2]
            breakthrough_now = cur[col_s] < cur[col_f] and cur[col_s] < cur[col_m]
            no_breakthrough_prev = prev[col_s] >= prev[col_f] or prev[col_s] >= prev[col_m]
            if not (breakthrough_now and no_breakthrough_prev):
                continue
            tangle_count = 0
            for i in range(len(monthly) - 2, -1, -1):
                row = monthly.iloc[i]
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
