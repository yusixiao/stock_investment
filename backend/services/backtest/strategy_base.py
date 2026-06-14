"""策略作者的公共契约(2026-06-14 迁入 backtest 子系统)。

历史:Phase 6.2 曾把 ``Strategy`` 放到顶层 ``strategies/base.py``,理由是
「策略作者无需感知 backend」。该理由已不成立(策略均为开发者自写、与回测引擎深度耦合),
故整体迁入 ``backend/services/backtest/`` 下,并将原 ``base.py`` 的 ``ParamAccessor``
合并到此文件,统一从 ``services.backtest.strategy_base`` 导入。
"""


class ParamAccessor:
    def __init__(self, params: dict, overrides: dict = None):
        self._values = {}
        self._types = {}
        for key, conf in params.items():
            self._values[key] = conf["default"]
            self._types[key] = conf.get("type", "")
        if overrides:
            for key, val in overrides.items():
                if key in self._values:
                    # 兼容两种格式：覆盖值可能是原始值(如 8)，也可能是完整定义(如 {"default": 8, ...})
                    if isinstance(val, dict) and "default" in val:
                        self._values[key] = val["default"]
                    else:
                        self._values[key] = val
        # 根据 params 中声明的 type 或 default 值类型，强制转换字符串为数值
        for key in self._values:
            v = self._values[key]
            if isinstance(v, str):
                t = self._types.get(key, "")
                if t == "int":
                    self._values[key] = int(v)
                elif t == "float":
                    self._values[key] = float(v)
                elif t == "" and params.get(key, {}).get("default") is not None:
                    default_val = params[key]["default"]
                    if isinstance(default_val, int):
                        try:
                            self._values[key] = int(v)
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(default_val, float):
                        try:
                            self._values[key] = float(v)
                        except (ValueError, TypeError):
                            pass

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._values:
            return self._values[name]
        raise AttributeError(f"No parameter named '{name}'")


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
