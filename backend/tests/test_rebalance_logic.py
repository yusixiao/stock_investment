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
