import sys
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy


class DividendYearsScreener(ScreenerStrategy):
    name = "累计分红年数筛选"
    description = "筛选累计现金分红年数达到指定年数的股票"
    frequency = "daily"

    params = {
        "min_years": {"default": 5},
    }

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            df = ctx.get_dividend(sym)
            if df is None:
                continue
            col = "现金分红-现金分红比例"
            if col not in df.columns:
                continue
            valid = df[col].apply(lambda v: isinstance(v, (int, float)) and not math.isnan(v) and v > 0)
            years = set()
            for idx in valid[valid].index:
                report_date = str(df.loc[idx, "报告期"])
                years.add(report_date[:4])
            if len(years) >= self.p.min_years:
                result.append(sym)
        return result
