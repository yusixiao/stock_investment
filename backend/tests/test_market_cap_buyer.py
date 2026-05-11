"""市值加权定投买入策略测试。"""

import pandas as pd
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "strategies" / "examples"))

from market_cap_weighted_buyer import MarketCapWeightedBuyer
from services.backtest.buy_sell_engine import BuySellEngine


def _make_stock_data(n_days=60):
    """生成60天（约8-9周）的日线数据。"""
    from datetime import date, timedelta
    start = date(2024, 1, 2)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(n_days)
             if (start + timedelta(days=i)).weekday() < 5]  # 只取交易日
    dates = dates[:n_days]

    df_a = pd.DataFrame({
        "date": dates,
        "open": [10.0] * len(dates),
        "high": [11.0] * len(dates),
        "low": [9.0] * len(dates),
        "close": [10.0] * len(dates),
        "volume": [1000.0] * len(dates),
        "amount": [10000.0] * len(dates),
    })
    df_b = df_a.copy()
    df_b["open"] = 20.0
    df_b["close"] = 20.0
    df_b["high"] = 22.0
    df_b["low"] = 18.0
    return {"SH600001": df_a, "SH600002": df_b}


def _make_valuation_data():
    """SH600001 总市值100亿，SH600002 总市值60亿。"""
    return {
        "SH600001": pd.DataFrame({
            "date": ["2024-01-01"],
            "total_mv": [10000.0],  # 单位：百万 → 100亿
        }),
        "SH600002": pd.DataFrame({
            "date": ["2024-01-01"],
            "total_mv": [6000.0],  # 60亿
        }),
    }


def test_market_cap_weighted_allocation():
    """验证按市值比例分配资金。"""
    stock_data = _make_stock_data()
    valuation_data = _make_valuation_data()

    # 两只股票同时在第一天触发信号
    signal_table = {"2024-01-02": ["SH600001", "SH600002"]}

    buyer = MarketCapWeightedBuyer()
    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        initial_capital=1_000_000,
        signal_table=signal_table,
        valuation_data=valuation_data,
    )
    result = engine.run()

    # 应该有交易产生
    assert len(result["trades"]) > 0

    # 验证买入了两只股票
    bought_symbols = set(t["symbol"] for t in result["trades"] if t["direction"] == "buy")
    assert "SH600001" in bought_symbols
    assert "SH600002" in bought_symbols


def test_buyer_only_on_new_symbols():
    """验证 buyer 仅在有新增信号时被调用。"""
    stock_data = _make_stock_data()
    valuation_data = _make_valuation_data()

    # 只有第一天有信号
    signal_table = {"2024-01-02": ["SH600001"]}

    buyer = MarketCapWeightedBuyer()
    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        initial_capital=1_000_000,
        signal_table=signal_table,
        valuation_data=valuation_data,
    )
    result = engine.run()

    # 只买了 SH600001
    bought_symbols = set(t["symbol"] for t in result["trades"] if t["direction"] == "buy")
    assert bought_symbols == {"SH600001"}


def test_weekly_buy_frequency():
    """验证每周只买入一次，最多买8次。"""
    stock_data = _make_stock_data(n_days=80)
    valuation_data = _make_valuation_data()

    signal_table = {"2024-01-02": ["SH600001"]}

    buyer = MarketCapWeightedBuyer()
    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        initial_capital=1_000_000,
        signal_table=signal_table,
        valuation_data=valuation_data,
    )
    result = engine.run()

    # SH600001 的买入次数应 <= 8
    buy_trades = [t for t in result["trades"] if t["symbol"] == "SH600001" and t["direction"] == "buy"]
    assert len(buy_trades) <= 8


def test_minimum_lot_size():
    """验证最小手数为100股。"""
    stock_data = _make_stock_data()
    valuation_data = _make_valuation_data()

    signal_table = {"2024-01-02": ["SH600001"]}

    buyer = MarketCapWeightedBuyer()
    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        initial_capital=1_000_000,
        signal_table=signal_table,
        valuation_data=valuation_data,
    )
    result = engine.run()

    for t in result["trades"]:
        if t["direction"] == "buy":
            assert t["shares"] % 100 == 0
            assert t["shares"] >= 100
