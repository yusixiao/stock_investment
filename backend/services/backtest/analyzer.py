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

    # 单边 trade 列表 → round-trip 配对(FIFO,按 symbol 分组)
    round_trips = pair_round_trips(trades)

    win_count = 0
    loss_count = 0
    win_pnl_sum = 0.0
    loss_pnl_sum = 0.0
    win_pct_sum = 0.0
    loss_pct_sum = 0.0
    for rt in round_trips:
        if rt["pnl"] > 0:
            win_count += 1
            win_pnl_sum += rt["pnl"]
            win_pct_sum += rt["pnl_pct"]
        else:
            loss_count += 1
            loss_pnl_sum += abs(rt["pnl"])
            loss_pct_sum += rt["pnl_pct"]  # 负值,保留符号

    n_round_trips = len(round_trips)
    win_rate = win_count / n_round_trips if n_round_trips > 0 else 0.0

    # profit_factor:总盈利金额 / 总亏损金额(经典定义)
    if loss_pnl_sum > 0:
        profit_factor = win_pnl_sum / loss_pnl_sum
    elif win_pnl_sum > 0:
        # 全胜:用极大值表征(避免 inf 干扰前端显示)
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    avg_win = win_pct_sum / win_count if win_count > 0 else 0.0
    avg_loss = loss_pct_sum / loss_count if loss_count > 0 else 0.0  # 保持负号

    total_trades = len(trades)  # 单边事件总数(buy + sell)

    total_trade_amount = sum(t.get("amount", 0) for t in trades)
    avg_daily_turnover = total_trade_amount / len(values) if values else 0
    avg_daily_value = sum(values) / len(values) if values else 1
    daily_turnover_rate = (
        avg_daily_turnover / avg_daily_value if avg_daily_value > 0 else 0
    )

    return {
        "total_return": round(total_return, 6),
        "annualized_return": round(annualized_return, 6),
        "max_drawdown": round(max_drawdown, 6),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "total_trades": total_trades,
        "round_trip_count": n_round_trips,
        "daily_turnover_rate": round(daily_turnover_rate, 6),
    }


def pair_round_trips(trades: list[dict]) -> list[dict]:
    """单边 buy/sell 事件 → 按 symbol FIFO 配对成 round-trip。

    每条 round-trip 包含前端期望的字段:
        symbol, direction, entry_date, exit_date, entry_price, exit_price,
        shares, pnl, pnl_pct, hold_days
    pnl 为净盈亏(扣手续费/印花税),pnl_pct 为相对买入成本的小数收益率。
    """
    # 按 symbol 维护各自的买入队列(FIFO)
    open_buys: dict[str, list[dict]] = {}
    rts: list[dict] = []
    for t in trades:
        sym = t.get("symbol", "")
        if t["direction"] == "buy":
            open_buys.setdefault(sym, []).append(t)
        elif t["direction"] == "sell":
            queue = open_buys.get(sym) or []
            remaining = int(t["shares"])
            sell_price = float(t["price"])
            sell_date = t.get("date", "")
            sell_comm = float(t.get("commission", 0)) + float(t.get("tax", 0))
            # 卖出 fee 按本笔 sell 在多个 buy 间按 share 数比例分摊
            total_sell_shares = remaining
            while remaining > 0 and queue:
                buy = queue[0]
                avail = int(buy["shares"]) - int(buy.get("_consumed", 0))
                take = min(avail, remaining)
                buy_price = float(buy["price"])
                buy_comm_full = float(buy.get("commission", 0))
                buy_comm = (
                    buy_comm_full * take / int(buy["shares"]) if buy["shares"] else 0.0
                )
                sell_comm_part = (
                    sell_comm * take / total_sell_shares if total_sell_shares else 0.0
                )
                cost = buy_price * take + buy_comm
                proceeds = sell_price * take - sell_comm_part
                pnl = proceeds - cost
                pnl_pct = pnl / cost if cost > 0 else 0.0
                hold_days = _date_diff(buy.get("date", ""), sell_date)
                rts.append(
                    {
                        "symbol": sym,
                        "direction": "long",
                        "entry_date": buy.get("date", ""),
                        "exit_date": sell_date,
                        "entry_price": buy_price,
                        "exit_price": sell_price,
                        "shares": take,
                        "pnl": round(pnl, 4),
                        "pnl_pct": round(pnl_pct, 6),
                        "hold_days": hold_days,
                    }
                )
                buy["_consumed"] = int(buy.get("_consumed", 0)) + take
                if buy["_consumed"] >= int(buy["shares"]):
                    queue.pop(0)
                remaining -= take
            # 卖出剩余(无对应买入,异常情况)忽略
    return rts


def _date_diff(d1: str, d2: str) -> int:
    try:
        a = datetime.strptime(d1, "%Y-%m-%d")
        b = datetime.strptime(d2, "%Y-%m-%d")
        return (b - a).days
    except Exception:
        return 0


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
        "profit_factor": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "total_trades": 0,
        "round_trip_count": 0,
        "daily_turnover_rate": 0.0,
    }
