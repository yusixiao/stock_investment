import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import pandas as pd
from services.backtest.base import ScreenerStrategy


class MaTangleBreakoutScreener(ScreenerStrategy):
    name = "月线均线缠绕"
    description = "月线均线缠绕后发散：缠绕N月（MA20<MA5）→ 之后M月内MA5/MA20发散且MA5>MA10>MA20且成交量连续阳线"
    frequency = "monthly"

    params = {
        "fast": {"default": 5},
        "mid": {"default": 10},
        "slow": {"default": 20},
        "threshold": {"default": 0.05},
        "tangle_months": {"default": 2},
        "spread_months": {"default": 6},
        "spread_threshold": {"default": 0.01},
        "vol_red_bars": {"default": 4},
    }

    def _max_consecutive_red(self, rows):
        max_run = 0
        cur_run = 0
        for _, row in rows.iterrows():
            if row["close"] >= row["open"]:
                cur_run += 1
                max_run = max(max_run, cur_run)
            else:
                cur_run = 0
        return max_run

    def _is_tangle(self, df, end, col_f, col_m, col_s):
        tm = self.p.tangle_months
        if end < tm - 1:
            return False
        for i in range(end - tm + 1, end + 1):
            row = df.iloc[i]
            avg = (row[col_f] + row[col_m] + row[col_s]) / 3.0
            if avg == 0:
                return False
            if (abs(row[col_f] - avg) / avg > self.p.threshold or
                    abs(row[col_m] - avg) / avg > self.p.threshold or
                    abs(row[col_s] - avg) / avg > self.p.threshold):
                return False
        last = df.iloc[end]
        return last[col_s] < last[col_f]

    def _check_spread_bar(self, row, col_f, col_m, col_s):
        avg = (row[col_f] + row[col_m] + row[col_s]) / 3.0
        if avg == 0:
            return False
        if (abs(row[col_f] - avg) / avg <= self.p.spread_threshold or
                abs(row[col_s] - avg) / avg <= self.p.spread_threshold):
            return False
        return row[col_f] > row[col_m] > row[col_s]

    def screen(self, ctx, symbols):
        result = []
        need_bars = self.p.slow + self.p.tangle_months + self.p.spread_months + 2
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

            n = len(df)
            tm = self.p.tangle_months
            sm = self.p.spread_months
            if n < tm + 1:
                continue

            matched = False
            for tangle_end in range(max(tm - 1, n - sm - tm), n - 1):
                if not self._is_tangle(df, tangle_end, col_f, col_m, col_s):
                    continue

                spread_start = tangle_end + 1
                spread_rows = df.iloc[spread_start:n]
                if len(spread_rows) == 0 or len(spread_rows) > sm:
                    continue

                all_spread = all(
                    self._check_spread_bar(spread_rows.iloc[j], col_f, col_m, col_s)
                    for j in range(len(spread_rows))
                )
                if not all_spread:
                    continue

                if self._max_consecutive_red(spread_rows) >= self.p.vol_red_bars:
                    matched = True
                    break

            if matched:
                result.append(sym)
        return result
