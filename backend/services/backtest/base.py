"""回测内部基础工具(Phase 6.2 精简后仅保留 ParamAccessor)。

策略作者公共契约 ``Strategy`` 已移至 ``strategies/base.py``;
旧的 ``BaseStrategy / ScreenerStrategy / TraderStrategy / BuyStrategy / SellStrategy``
五类已在 Phase 6.2 删除。
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
