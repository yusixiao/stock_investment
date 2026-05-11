import pandas as pd
from services.backtest.context import TraderContext
from services.backtest.portfolio import Portfolio


def test_available_cash_returns_portfolio_cash():
    df = pd.DataFrame([
        {"date": "2024-01-02", "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.1, "volume": 1000000.0, "amount": 10000000.0},
        {"date": "2024-01-03", "open": 10.1, "high": 10.6, "low": 9.6, "close": 10.2, "volume": 1000000.0, "amount": 10000000.0},
    ])
    stock_data = {"000001": df}
    portfolio = Portfolio(initial_capital=500_000)

    ctx = TraderContext(
        stock_data=stock_data,
        current_idx=0,
        portfolio=portfolio,
        broker_submit=lambda *a: None,
        selected_symbols=["000001"],
    )

    assert ctx.available_cash == 500_000

    portfolio.cash = 123456.78
    assert ctx.available_cash == 123456.78
