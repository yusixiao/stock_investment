import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy


class MonthlyLowScreener(ScreenerStrategy):
    name = "月线历史低位"
    description = "当月low处于过去N年月线最低价的指定范围内"
    frequency = "monthly"

    params = {
        "years": {"default": 3, "label": "回看年数", "type": "int"},
        "range_pct": {"default": 20, "label": "范围百分比", "type": "int"},
    }

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        years = self.p.years
        lookback = years * 12
        range_ratio = 1 + self.p.range_pct / 100.0
        result = []

        for sym in symbols:
            hist = ctx.get_history(sym, lookback + 1)
            if hist is None or len(hist) < lookback + 1:
                continue

            current_low = hist.iloc[-1]["low"]
            past_data = hist.iloc[-(lookback + 1):-1]
            hist_min_low = past_data["low"].min()

            if current_low <= hist_min_low * range_ratio:
                result.append(sym)

        return result
