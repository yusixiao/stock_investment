import sys
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import pandas as pd
from services.backtest.base import ScreenerStrategy

logger = logging.getLogger(__name__)


class MonthlyVolumeRedScreener(ScreenerStrategy):
    name = "月线成交量连续红柱"
    description = "月线连续N个月收盘价>=开盘价（阳线/平收），成交量柱为红色"
    frequency = "monthly"

    params = {
        "consecutive_months": {"default": 4},
    }

    def screen(self, ctx, symbols):
        result = []
        need_bars = self.p.consecutive_months + 1
        for sym in symbols:
            history = ctx.get_history(sym, need_bars)
            if len(history) < self.p.consecutive_months:
                logger.debug("%s: 历史数据不足(%d < %d)，跳过", sym, len(history), self.p.consecutive_months)
                continue
            df = pd.DataFrame(history)
            recent = df.tail(self.p.consecutive_months)
            if (recent["close"] >= recent["open"]).all():
                result.append(sym)
            else:
                logger.debug("%s: 最近%d月未全部收阳，不符合", sym, self.p.consecutive_months)
        return result
