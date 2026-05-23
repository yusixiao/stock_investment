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
        # Phase 1.2 的 tuple 形态(向后兼容):
        self.pass_logs: list[tuple[str, str, dict]] = []
        self.reject_logs: list[tuple[str, str, str, dict]] = []
        self.flow_logs: list[tuple[str, dict]] = []
        # Phase 2.2 新增结构化记录,供策略集成测使用:
        self.log_records: dict[str, list[dict]] = {
            "pass": [],
            "reject": [],
            "flow": [],
        }

        # 下单记录(测试可断言)
        self.orders: list[tuple[str, int]] = []

        # 因子记录(策略雷达使用):{symbol: {factor_name: value}}
        self._factors: dict[str, dict[str, Any]] = {}

    # ===== 因子记录 =====
    def record_factor(self, symbol: str, name: str, value: Any) -> None:
        self._factors.setdefault(symbol, {})[name] = value

    def get_factors(self, symbol: str) -> dict[str, Any]:
        return dict(self._factors.get(symbol, {}))

    def get_all_factors(self) -> dict[str, dict[str, Any]]:
        return self._factors

    def reset_factors(self) -> None:
        self._factors = {}

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
        self.log_records["pass"].append({"symbol": symbol, "stage": stage, **values})

    def log_reject(
        self, symbol: str, stage: str, reason: str = "", **values: Any
    ) -> None:
        # reason 可作为位置参数(Phase 1 调用风格)或关键字参数(Phase 2.2 风格)
        self.reject_logs.append((symbol, stage, reason, dict(values)))
        self.log_records["reject"].append(
            {"symbol": symbol, "stage": stage, "reason": reason, **values}
        )

    def log_flow(self, stage: str, **counts: Any) -> None:
        self.flow_logs.append((stage, dict(counts)))
        self.log_records["flow"].append({"stage": stage, **counts})

    # ===== 结构化日志查询辅助 =====
    def passed_symbols(self, stage: str) -> list[str]:
        return [r["symbol"] for r in self.log_records["pass"] if r["stage"] == stage]

    def rejected_symbols(self, stage: str) -> list[str]:
        return [r["symbol"] for r in self.log_records["reject"] if r["stage"] == stage]

    # ===== 下单 =====
    def order_shares(self, symbol: str, shares: int) -> None:
        self.orders.append((symbol, shares))

    # ===== 集成测便捷 setter(Phase 2.4) =====
    # 将简单的 mapping 转成各 utils 函数所需的真实数据结构,便于策略集成测一次性铺数据。
    def set_dividend_years(self, mapping: dict[str, int]) -> None:
        """将 {symbol: years} 转成 dividend.filter_by_dividend_years 期望的 DataFrame。

        每个 year 生成一行 cash > 0 的记录(English schema:date / cash_dividend)。
        """
        import pandas as pd

        for sym, years in mapping.items():
            rows = [
                {"date": f"{2000 + i}-12-31", "cash_dividend": 1.0}
                for i in range(int(years))
            ]
            self._dividend[sym] = pd.DataFrame(rows)

    def set_pe_pb(self, mapping: dict[str, tuple[float, float]]) -> None:
        """{symbol: (pe, pb)} → valuation 字典(English schema:peTTM / pbMRQ)。"""
        for sym, (pe, pb) in mapping.items():
            entry = self._valuation.setdefault(sym, {})
            entry["peTTM"] = pe
            entry["pbMRQ"] = pb

    def set_roe(self, mapping: dict[str, float]) -> None:
        """{symbol: roe%} → financial 字典(English schema:ROEJQ)。"""
        for sym, roe in mapping.items():
            entry = self._financial.setdefault(sym, {})
            entry["ROEJQ"] = roe

    def set_ma_tangle_breakout_hits(self, hits: set[str]) -> None:
        """记录 detect_ma_tangle_breakout 应命中的 symbols。

        本身并不替换 utils 函数,需要测试用 monkeypatch 注入。
        见 `make_tangle_breakout_stub`。
        """
        self._tangle_hits = set(hits)


def make_tangle_breakout_stub(ctx: "MockContext"):
    """生成可替换 strategies.utils.kline.detect_ma_tangle_breakout 的 stub。

    短路逻辑:symbol ∈ ctx._tangle_hits → 返回 True,否则 False;同步打 log。
    """

    hits = getattr(ctx, "_tangle_hits", set())

    def _stub(_ctx, symbol, **_kwargs):
        stage = "kline.ma_tangle"
        if symbol in hits:
            _ctx.log_pass(symbol, stage)
            return True
        _ctx.log_reject(symbol, stage, "no_hit")
        return False

    return _stub
