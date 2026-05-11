import sys
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy

logger = logging.getLogger(__name__)


class RoeScreener(ScreenerStrategy):
    name = "ROE筛选"
    description = "筛选净资产收益率(ROE)不低于指定值的股票"
    frequency = "daily"

    params = {
        "min_roe": {"default": 10},
    }

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            fin = ctx.get_financial(sym)
            if fin is None:
                logger.debug("%s: 无财报数据，跳过", sym)
                continue
            roe = fin.get("净资产收益率")
            if roe is None:
                logger.debug("%s: ROE 数据缺失，跳过", sym)
                continue
            if roe >= self.p.min_roe:
                result.append(sym)
            else:
                logger.debug("%s: ROE=%.2f < 阈值%.2f，不符合", sym, roe, self.p.min_roe)
        return result
