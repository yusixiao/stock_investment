import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pandas as pd
from services.backtest.buy_sell_engine import BuySellEngine
from equal_weight_buyer import EqualWeightBuyer
from pe_sell import PESell


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 22)]
    data = {}
    for sym in ["000001", "000002"]:
        base = 10.0 if sym == "000001" else 20.0
        rows = []
        for i, d in enumerate(dates):
            price = base + i * 0.1
            rows.append({
                "date": d,
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price + 0.05,
                "volume": 1000000.0,
                "amount": 10000000.0,
            })
        data[sym] = pd.DataFrame(rows)
    return data


def _make_valuation_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 22)]
    val = {}
    for sym in ["000001", "000002"]:
        rows = []
        for i, d in enumerate(dates):
            pe = 20.0 + i * 3
            rows.append({"date": d, "pe": pe})
        val[sym] = pd.DataFrame(rows)
    return val


def test_equal_weight_buyer_and_pe_sell():
    stock_data = _make_stock_data()
    valuation_data = _make_valuation_data()

    signal_table = {
        "2024-01-03": ["000001", "000002"],
    }

    buyer = EqualWeightBuyer({"max_positions": 2})
    seller = PESell({"pe_threshold": 35.0})

    engine = BuySellEngine(
        stock_data=stock_data,
        buyer=buyer,
        seller=seller,
        initial_capital=1_000_000,
        signal_table=signal_table,
        valuation_data=valuation_data,
    )
    result = engine.run()

    trades = result["trades"]
    buy_trades = [t for t in trades if t["direction"] == "buy"]
    sell_trades = [t for t in trades if t["direction"] == "sell"]

    assert len(buy_trades) >= 1
    assert len(sell_trades) >= 1
