import sys
import math
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy

logger = logging.getLogger(__name__)


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
                logger.debug("%s: 无分红数据，跳过", sym)
                continue
            col = "现金分红-现金分红比例"
            if col not in df.columns:
                logger.debug("%s: 缺少分红比例列，跳过", sym)
                continue
            valid = df[col].apply(lambda v: isinstance(v, (int, float)) and not math.isnan(v) and v > 0)
            years = set()
            for idx in valid[valid].index:
                report_date = str(df.loc[idx, "报告期"])
                years.add(report_date[:4])
            if len(years) >= self.p.min_years:
                result.append(sym)
            else:
                logger.debug("%s: 分红年数%d < 阈值%d，不符合", sym, len(years), self.p.min_years)
        return result
