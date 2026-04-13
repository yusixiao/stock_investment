import math
from datetime import datetime


def compute_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    initial_capital: float,
) -> dict:
    if not equity_curve:
        return _empty_metrics()

    values = [e["total_value"] for e in equity_curve]
    dates = [e["date"] for e in equity_curve]

    final_value = values[-1]
    total_return = (final_value - initial_capital) / initial_capital

    if len(dates) >= 2:
        start_dt = datetime.strptime(dates[0], "%Y-%m-%d")
        end_dt = datetime.strptime(dates[-1], "%Y-%m-%d")
        years = (end_dt - start_dt).days / 365.25
    else:
        years = 0

    if years > 0 and total_return > -1:
        annualized_return = (1 + total_return) ** (1 / years) - 1
    else:
        annualized_return = 0.0

    max_drawdown = _calc_max_drawdown(values)

    daily_returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            daily_returns.append((values[i] - values[i - 1]) / values[i - 1])

    sharpe_ratio = _calc_sharpe(daily_returns, risk_free_rate=0.03)

    sell_trades = [t for t in trades if t["direction"] == "sell"]
    buy_trades = [t for t in trades if t["direction"] == "buy"]

    win_count = 0
    win_profits = 0.0
    loss_profits = 0.0
    for i, sell in enumerate(sell_trades):
        if i < len(buy_trades):
            pnl = (sell["price"] - buy_trades[i]["price"]) * sell["shares"]
            if pnl > 0:
                win_count += 1
                win_profits += pnl
            else:
                loss_profits += abs(pnl)

    trade_count = len(trades)
    n_round_trips = min(len(sell_trades), len(buy_trades))
    win_rate = win_count / n_round_trips if n_round_trips > 0 else 0.0
    profit_loss_ratio = (win_profits / win_count) / (loss_profits / (n_round_trips - win_count)) if (n_round_trips > win_count > 0 and loss_profits > 0) else 0.0

    total_trade_amount = sum(t.get("amount", 0) for t in trades)
    avg_daily_turnover = total_trade_amount / len(values) if values else 0
    avg_daily_value = sum(values) / len(values) if values else 1
    daily_turnover_rate = avg_daily_turnover / avg_daily_value if avg_daily_value > 0 else 0

    return {
        "total_return": round(total_return, 6),
        "annualized_return": round(annualized_return, 6),
        "max_drawdown": round(max_drawdown, 6),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "win_rate": round(win_rate, 4),
        "profit_loss_ratio": round(profit_loss_ratio, 4),
        "trade_count": trade_count,
        "daily_turnover_rate": round(daily_turnover_rate, 6),
    }


def _calc_max_drawdown(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _calc_sharpe(daily_returns: list[float], risk_free_rate: float = 0.03) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mean_r = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std_r = math.sqrt(variance)
    if std_r == 0:
        return 0.0
    annual_return = mean_r * 252
    annual_std = std_r * math.sqrt(252)
    return (annual_return - risk_free_rate) / annual_std


def _empty_metrics() -> dict:
    return {
        "total_return": 0.0,
        "annualized_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "win_rate": 0.0,
        "profit_loss_ratio": 0.0,
        "trade_count": 0,
        "daily_turnover_rate": 0.0,
    }
