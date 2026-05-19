"""utils 函数单测共用的 MockContext。

Phase 1 / 2 阶段真实 Context 尚未重写完(在 Phase 3),utils 函数测试通过此 mock 隔离。
真实 Context 接口见 spec § Context (D1 完成后逐步实现)。
"""

from typing import Any


class MockContext:
    """模拟 Context,提供 utils 函数所需的所有接口。"""

    def __init__(
        self,
        dividend: dict | None = None,
        financial: dict | None = None,
        valuation: dict | None = None,
        history: dict | None = None,
        price: dict | None = None,
        target_symbols: list | None = None,
        new_symbols: list | None = None,
        available_cash: float = 1_000_000.0,
        current_date: str | None = None,
        current_idx: int = 0,
    ):
        self._dividend = dividend or {}
        self._financial = financial or {}
        self._valuation = valuation or {}
        self._history = history or {}
        self._price = price or {}
        self.target_symbols = list(target_symbols or [])
        self.new_symbols = list(new_symbols or [])
        self.available_cash = available_cash
        self.current_date = current_date
        self.current_idx = current_idx

        # 日志记录(测试可断言)
        self.pass_logs: list[tuple[str, str, dict]] = []
        self.reject_logs: list[tuple[str, str, str, dict]] = []
        self.flow_logs: list[tuple[str, dict]] = []

        # 下单记录(测试可断言)
        self.orders: list[tuple[str, int]] = []

    # ===== 数据访问 =====
    def get_dividend(self, symbol: str):
        return self._dividend.get(symbol)

    def get_financial(self, symbol: str):
        return self._financial.get(symbol)

    def get_valuation(self, symbol: str):
        return self._valuation.get(symbol)

    def get_history(self, symbol: str, n: int, period: str = "daily"):
        # period 在 mock 中不切换数据源,留接口给真实 ctx 实现。
        # 测试如需区分 period,可注入 history={"A__weekly": [...], "A__daily": [...]}
        # 并按 f"{symbol}__{period}" 查找(本 mock 简化处理:优先 symbol__period,fallback symbol)
        keyed = self._history.get(f"{symbol}__{period}")
        if keyed is not None:
            bars = keyed
        else:
            bars = self._history.get(symbol)
        if bars is None:
            return []
        return bars[-n:] if n > 0 else bars

    def get_price(self, symbol: str, period: str = "daily"):
        sym_data = self._price.get(symbol)
        if sym_data is None:
            return None
        return sym_data.get(period)

    # ===== 日志 =====
    def log_pass(self, symbol: str, stage: str, **values: Any) -> None:
        self.pass_logs.append((symbol, stage, dict(values)))

    def log_reject(self, symbol: str, stage: str, reason: str, **values: Any) -> None:
        self.reject_logs.append((symbol, stage, reason, dict(values)))

    def log_flow(self, stage: str, **counts: Any) -> None:
        self.flow_logs.append((stage, dict(counts)))

    # ===== 下单 =====
    def order_shares(self, symbol: str, shares: int) -> None:
        self.orders.append((symbol, shares))
