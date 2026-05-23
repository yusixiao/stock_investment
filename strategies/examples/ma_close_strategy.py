"""月线 MA5 / MA20 接近策略(MaCloseStrategy)。

筛选月线 |MA5 - MA20| / MA20 <= threshold(默认 1%)的股票,
仅作选股用,不下单(无 on_buy / on_sell)— 适合在策略雷达里直观查看
均线粘合的标的池。
"""

from strategies.base import Strategy
from strategies.utils import kline


class MaCloseStrategy(Strategy):
    name = "月线MA5MA20粘合策略"
    description = "月线快慢均线接近度筛选 — |MA5 - MA20| / MA20 <= 阈值(默认 1%)。"
    frequency = "monthly"
    frequency_overridable = False

    params = {
        "ma_fast": {"default": 5, "type": "int", "label": "快速均线"},
        "ma_slow": {"default": 20, "type": "int", "label": "慢速均线"},
        "threshold": {
            "default": 0.01,
            "type": "float",
            "label": "差值阈值(0.01 = 1%)",
        },
    }

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))
        result = kline.filter_by_ma_close(
            ctx,
            symbols,
            fast=self.p.ma_fast,
            slow=self.p.ma_slow,
            threshold=self.p.threshold,
            freq="monthly",
        )
        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(result))
        return result
