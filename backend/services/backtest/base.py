class ParamAccessor:
    def __init__(self, params: dict, overrides: dict = None):
        self._values = {}
        for key, conf in params.items():
            self._values[key] = conf["default"]
        if overrides:
            for key, val in overrides.items():
                if key in self._values:
                    # 兼容两种格式：覆盖值可能是原始值(如 8)，也可能是完整定义(如 {"default": 8, ...})
                    if isinstance(val, dict) and "default" in val:
                        self._values[key] = val["default"]
                    else:
                        self._values[key] = val

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._values:
            return self._values[name]
        raise AttributeError(f"No parameter named '{name}'")


class BaseStrategy:
    name: str = ""
    description: str = ""
    params: dict = {}
    strategy_type: str = "base"

    def __init__(self, param_overrides: dict = None):
        self.p = ParamAccessor(self.params, overrides=param_overrides)


class ScreenerStrategy(BaseStrategy):
    strategy_type = "screener"
    frequency: str = "daily"

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        raise NotImplementedError


class TraderStrategy(BaseStrategy):
    strategy_type = "trader"
    settings: dict = {}

    def __init__(self, param_overrides: dict = None):
        super().__init__(param_overrides)
        defaults = {
            "initial_capital": 1_000_000,
            "commission_rate": 0.0003,
            "slippage": 0.002,
        }
        merged = {**defaults, **self.__class__.settings}
        self.settings = merged

    def on_bar(self, ctx):
        raise NotImplementedError


class BuyStrategy(BaseStrategy):
    strategy_type = "buy"

    def on_bar(self, ctx):
        raise NotImplementedError


class SellStrategy(BaseStrategy):
    strategy_type = "sell"

    def on_bar(self, ctx):
        raise NotImplementedError
