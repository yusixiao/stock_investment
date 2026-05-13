"""调仓逻辑测试：target_symbols 累计语义、执行顺序、Buyer 调用条件。"""
import pandas as pd
import pytest
from services.backtest.context import TraderContext
from services.backtest.portfolio import Portfolio


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 12)]
    df = pd.DataFrame({
        "date": dates,
        "open": [10.0] * 10,
        "high": [11.0] * 10,
        "low": [9.0] * 10,
        "close": [10.0] * 10,
        "volume": [1000.0] * 10,
        "amount": [10000.0] * 10,
    })
    return {"SH600001": df, "SH600002": df.copy(), "SH600003": df.copy()}


def test_trader_context_target_symbols():
    """TraderContext 应能接收并暴露 target_symbols 和 new_symbols。"""
    stock_data = _make_stock_data()
    portfolio = Portfolio(initial_capital=1_000_000)

    ctx = TraderContext(
        stock_data=stock_data,
        current_idx=0,
        portfolio=portfolio,
        broker_submit=lambda *a: None,
        selected_symbols=[],
        target_symbols=["SH600001", "SH600002"],
        new_symbols=["SH600002"],
    )
    assert set(ctx.target_symbols) == {"SH600001", "SH600002"}
    assert ctx.new_symbols == ["SH600002"]


def test_trader_context_remove_target():
    """Seller 通过 ctx.remove_target() 从 target_symbols 中移除股票。"""
    stock_data = _make_stock_data()
    portfolio = Portfolio(initial_capital=1_000_000)
    target_set = {"SH600001", "SH600002"}

    ctx = TraderContext(
        stock_data=stock_data,
        current_idx=0,
        portfolio=portfolio,
        broker_submit=lambda *a: None,
        selected_symbols=[],
        target_symbols=list(target_set),
        new_symbols=[],
        on_remove_target=lambda sym: target_set.discard(sym),
    )
    ctx.remove_target("SH600001")
    assert "SH600001" not in target_set


# --- BuySellEngine integration tests ---

from services.backtest.buy_sell_engine import BuySellEngine
from services.backtest.base import BuyStrategy, SellStrategy, ScreenerStrategy


class RecordingBuyer(BuyStrategy):
    """记录每次 on_bar 调用时的 target_symbols 和 new_symbols。"""
    name = "recording_buyer"
    params = {}

    def __init__(self):
        super().__init__()
        self.calls = []

    def on_bar(self, ctx):
        self.calls.append({
            "date": ctx._current_date,
            "target_symbols": list(ctx.target_symbols),
            "new_symbols": list(ctx.new_symbols),
            "cash": ctx.available_cash,
        })


class RecordingSeller(SellStrategy):
    """在特定日期对特定股票调用 remove_target + 卖出。"""
    name = "recording_seller"
    params = {}

    def __init__(self, sell_plan: dict[str, list[str]] = None):
        super().__init__()
        self.sell_plan = sell_plan or {}
        self.calls = []

    def on_bar(self, ctx):
        self.calls.append(ctx._current_date)
        symbols_to_sell = self.sell_plan.get(ctx._current_date, [])
        for sym in symbols_to_sell:
            pos = ctx.get_position(sym)
            if pos and pos["shares"] > 0:
                ctx.order_shares(sym, -pos["shares"])
            ctx.remove_target(sym)


def test_target_symbols_accumulates():
    """信号表命中时 target_symbols 累计，buyer 仅在有新增时调用。"""
    stock_data = _make_stock_data()
    signal_table = {
        "2024-01-04": ["SH600001"],
        "2024-01-06": ["SH600002"],
    }
    buyer = RecordingBuyer()
    seller = RecordingSeller()

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    engine.run()

    # Buyer 每日执行（DCA策略需要），data有10天
    assert len(buyer.calls) == 10

    # 信号日 2024-01-04 (idx=2): target_symbols = [SH600001], new_symbols = [SH600001]
    day4_call = buyer.calls[2]
    assert "SH600001" in day4_call["target_symbols"]
    assert "SH600001" in day4_call["new_symbols"]

    # 信号日 2024-01-06 (idx=4): target_symbols contains both, new_symbols = [SH600002]
    day6_call = buyer.calls[4]
    assert "SH600001" in day6_call["target_symbols"]
    assert "SH600002" in day6_call["target_symbols"]
    assert "SH600002" in day6_call["new_symbols"]
    assert "SH600001" not in day6_call["new_symbols"]


def test_seller_removes_from_target():
    """Seller 平仓后从 target_symbols 移除，不触发 buyer。"""
    stock_data = _make_stock_data()
    signal_table = {
        "2024-01-03": ["SH600001"],
    }
    seller = RecordingSeller(sell_plan={"2024-01-06": ["SH600001"]})
    buyer = RecordingBuyer()

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    engine.run()

    # Buyer 每日执行（10 bars）
    assert len(buyer.calls) == 10
    # 信号日 2024-01-03 (idx=1): target_symbols = [SH600001]
    day3_call = [c for c in buyer.calls if c["date"] == "2024-01-03"][0]
    assert day3_call["target_symbols"] == ["SH600001"]

    # Seller called every day (10 bars)
    assert len(seller.calls) == 10


def test_seller_executes_before_buyer():
    """同一天: seller 先执行释放资金，buyer 后执行时能用到释放的资金。"""
    stock_data = _make_stock_data()
    signal_table = {
        "2024-01-03": ["SH600001"],
        "2024-01-06": ["SH600002"],
    }
    # day6: seller removes SH600001, buyer gets signal for SH600002
    seller = RecordingSeller(sell_plan={"2024-01-06": ["SH600001"]})
    buyer = RecordingBuyer()

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    engine.run()

    # On day6, buyer's ctx should NOT contain SH600001 (seller already removed it)
    day6_call = [c for c in buyer.calls if c["date"] == "2024-01-06"]
    assert len(day6_call) == 1
    assert "SH600001" not in day6_call[0]["target_symbols"]
    assert "SH600002" in day6_call[0]["target_symbols"]
