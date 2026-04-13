class ParamAccessor:
    def __init__(self, params: dict, overrides: dict = None):
        self._values = {}
        for key, conf in params.items():
            self._values[key] = conf["default"]
        if overrides:
            for key, val in overrides.items():
                if key in self._values:
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
