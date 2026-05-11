import sys
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy

logger = logging.getLogger(__name__)


class PePbProductScreener(ScreenerStrategy):
    name = "PE*PB乘积筛选"
    description = "筛选PE(TTM)*PB乘积在指定范围内的股票"
    frequency = "daily"

    params = {
        "min_value": {"default": 0.0},
        "max_value": {"default": 22.0},
    }

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            val = ctx.get_valuation(sym)
            if val is None:
                logger.debug("%s: 无估值数据，跳过", sym)
                continue
            pe = val.get("pe_ttm")
            pb = val.get("pb")
            if pe is None or pb is None:
                logger.debug("%s: PE或PB缺失，跳过", sym)
                continue
            product = pe * pb
            if self.p.min_value <= product <= self.p.max_value:
                result.append(sym)
            else:
                logger.debug("%s: PE*PB=%.2f 不在[%.2f, %.2f]范围内", sym, product, self.p.min_value, self.p.max_value)
        return result
