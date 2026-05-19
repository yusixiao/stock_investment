"""策略作者的公共契约(2026-05-19 Phase 6.2 从 backend.services.backtest.base 迁出)。

把 ``Strategy`` 放到 ``strategies/`` 下符合「就近原则」,并反转依赖方向:
backend 内部的 engine 依赖 ``strategies.base.Strategy``,而策略作者无需感知 backend。

``ParamAccessor`` 仍住在 backend 内部(engine 使用),此处通过 import 桥接,
策略作者只需 ``from strategies.base import Strategy``。
"""

from services.backtest.base import ParamAccessor


class Strategy:
    """统一策略基类。

    一个 Strategy 同时拥有 screen / on_buy / on_sell 三个钩子。
    子类按需覆盖钩子;默认实现:
      - screen() → 返回全部输入 symbols(等价无筛选)
      - on_buy()  → pass(默认不买)
      - on_sell() → pass(默认永久持有)

    频率(frequency)语义见 spec D1.1:
      - frequency: "daily" | "weekly" | "monthly",指 screen() 调用节奏
      - frequency_overridable: 是否允许用户在 UI 改频率,默认 False(锁死)
    """

    name: str = ""
    description: str = ""
    params: dict = {}
    strategy_type: str = "strategy"
    frequency: str = "daily"
    frequency_overridable: bool = False
    settings: dict = {}

    def __init__(self, param_overrides: dict = None):
        self.p = ParamAccessor(self.params, overrides=param_overrides)
        defaults = {
            "initial_capital": 1_000_000,
            "commission_rate": 0.0003,
            "slippage": 0.002,
        }
        self.settings = {**defaults, **self.__class__.settings}

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        return list(symbols)

    def on_buy(self, ctx) -> None:
        pass

    def on_sell(self, ctx) -> None:
        pass
