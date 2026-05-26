"""沪深300 ETF 三方案回测对比

信号源:000300.SH 月线收盘
成交标的:510310.SH(close_qfq,反映真实投资者收益)
回测期:2014-01 ~ 2026-05(149 个月)

方案对比:
- 基线  : 745,000 一次性 buy & hold
- 方案1 : MA10/MA1 月线择时,信号触发时全仓 745,000(MA1 上穿 MA10 满仓,下穿清仓)
- 方案2 : 月定投 5,000 × 149 = 745,000

口径:每月最后一个交易日为决策日,次月首个交易日按当日 close_qfq 成交。
"""

from __future__ import annotations

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data/market/INDEX/daily/000300.SH.parquet"
ETF_PATH = ROOT / "data/market/ETF/daily/510310.SH.parquet"

START = "2014-01-01"
END = "2026-05-31"
TOTAL_AMOUNT = 745_000
DCA_MONTHLY = 5_000
MA_WINDOW = 10  # 方案1 MA 窗口


def load_data():
    idx = pd.read_parquet(INDEX_PATH)
    etf = pd.read_parquet(ETF_PATH)
    idx["date"] = pd.to_datetime(idx["date"])
    etf["date"] = pd.to_datetime(etf["date"])
    idx = idx.sort_values("date").reset_index(drop=True)
    etf = etf.sort_values("date").reset_index(drop=True)
    return idx, etf


def to_monthly(df: pd.DataFrame, price_col: str) -> pd.DataFrame:
    """每月最后一个交易日的收盘价"""
    df = df.copy()
    df["ym"] = df["date"].dt.to_period("M")
    last = df.groupby("ym").tail(1).reset_index(drop=True)
    return last[["date", "ym", price_col]].rename(columns={price_col: "close"})


def first_trading_day_each_month(df: pd.DataFrame, price_col: str) -> pd.DataFrame:
    df = df.copy()
    df["ym"] = df["date"].dt.to_period("M")
    first = df.groupby("ym").head(1).reset_index(drop=True)
    return first[["date", "ym", price_col]].rename(columns={price_col: "exec_price"})


def run_baseline(etf_first: pd.DataFrame) -> dict:
    """745,000 在窗口首月一次性买入并持有"""
    entry = etf_first.iloc[0]
    exit_ = etf_first.iloc[-1]
    shares = TOTAL_AMOUNT / entry["exec_price"]
    end_value = shares * exit_["exec_price"]
    return {
        "name": "基线 745,000 一次性持有",
        "invested": TOTAL_AMOUNT,
        "end_value": end_value,
        "total_return": end_value / TOTAL_AMOUNT - 1,
        "entry_date": entry["date"].date(),
        "exit_date": exit_["date"].date(),
        "n_months": len(etf_first),
    }


def run_timing(idx_monthly: pd.DataFrame, etf_first: pd.DataFrame) -> dict:
    """MA10/MA1 月线择时:MA1(当月收盘)上穿 MA10 → 全仓;下穿 → 清仓
    决策在月末 t,执行在 t+1 首个交易日。
    """
    idx_monthly = idx_monthly.copy()
    idx_monthly["ma"] = idx_monthly["close"].rolling(MA_WINDOW).mean()
    idx_monthly["signal_long"] = idx_monthly["close"] > idx_monthly["ma"]

    # 把信号 join 到 etf 月初执行价
    merged = etf_first.merge(idx_monthly[["ym", "signal_long"]], on="ym", how="left")
    # 决策信号是上一月末的 → shift 1 个月对齐到执行月
    merged["signal_eff"] = merged["signal_long"].shift(1)

    cash = TOTAL_AMOUNT
    shares = 0.0
    holding = False
    trades = []

    for _, row in merged.iterrows():
        sig = row["signal_eff"]
        if pd.isna(sig):
            continue
        price = row["exec_price"]
        if sig and not holding:
            shares = cash / price
            cash = 0.0
            holding = True
            trades.append(("BUY", row["date"].date(), price, shares))
        elif (not sig) and holding:
            cash = shares * price
            shares = 0.0
            holding = False
            trades.append(("SELL", row["date"].date(), price, cash))

    last_price = merged.iloc[-1]["exec_price"]
    end_value = cash + shares * last_price
    return {
        "name": f"方案1 MA{MA_WINDOW}/MA1 择时全仓 {TOTAL_AMOUNT:,}",
        "invested": TOTAL_AMOUNT,
        "end_value": end_value,
        "total_return": end_value / TOTAL_AMOUNT - 1,
        "n_trades": len(trades),
        "final_holding": holding,
    }


def run_dca(etf_first: pd.DataFrame) -> dict:
    """月定投 5,000,每月首个交易日按 close_qfq 买入"""
    shares = 0.0
    invested = 0.0
    cashflows = []  # (date, amount) 流出为负,流入为正
    for _, row in etf_first.iterrows():
        shares += DCA_MONTHLY / row["exec_price"]
        invested += DCA_MONTHLY
        cashflows.append((row["date"], -DCA_MONTHLY))
    last_price = etf_first.iloc[-1]["exec_price"]
    end_value = shares * last_price
    cashflows.append((etf_first.iloc[-1]["date"], end_value))
    return {
        "name": f"方案2 月定投 {DCA_MONTHLY:,} × {len(etf_first)} 月",
        "invested": invested,
        "end_value": end_value,
        "total_return": end_value / invested - 1,
        "n_months": len(etf_first),
        "cashflows": cashflows,
    }


def annualized(total_return: float, n_months: int) -> float:
    years = n_months / 12.0
    return (1 + total_return) ** (1 / years) - 1


def xirr(cashflows: list, guess: float = 0.1) -> float:
    """牛顿法解 XIRR(年化内部收益率)"""
    from datetime import datetime

    if not cashflows:
        return 0.0
    t0 = cashflows[0][0]
    if hasattr(t0, "to_pydatetime"):
        t0 = t0.to_pydatetime()

    def npv(rate: float) -> float:
        total = 0.0
        for d, amt in cashflows:
            if hasattr(d, "to_pydatetime"):
                d = d.to_pydatetime()
            years = (d - t0).days / 365.25
            total += amt / (1 + rate) ** years
        return total

    rate = guess
    for _ in range(100):
        f = npv(rate)
        # 数值微分
        df = (npv(rate + 1e-6) - f) / 1e-6
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if abs(new_rate - rate) < 1e-9:
            return new_rate
        rate = new_rate
    return rate


def main():
    idx, etf = load_data()

    # 信号源用月线收盘(指数)
    idx_monthly = to_monthly(
        idx[(idx["date"] >= "2013-01-01") & (idx["date"] <= END)], "close"
    )
    # 执行价用 ETF 每月首交易日 close_qfq
    etf_in_window = etf[(etf["date"] >= START) & (etf["date"] <= END)]
    etf_first = first_trading_day_each_month(etf_in_window, "close_qfq")

    print(
        f"窗口: {etf_first.iloc[0]['date'].date()} ~ {etf_first.iloc[-1]['date'].date()}"
    )
    print(f"月数: {len(etf_first)}\n")

    n_months = len(etf_first)

    results = [
        run_baseline(etf_first),
        run_timing(idx_monthly, etf_first),
        run_dca(etf_first),
    ]

    print(f"{'方案':<40} {'投入':>12} {'末值':>14} {'总收益':>10} {'年化':>14}")
    print("-" * 96)
    for r in results:
        if "cashflows" in r:
            ann = xirr(r["cashflows"])
            ann_label = f"{ann * 100:>7.2f}% (IRR)"
        else:
            ann = annualized(r["total_return"], n_months)
            ann_label = f"{ann * 100:>7.2f}%      "
        print(
            f"{r['name']:<40} {r['invested']:>12,.0f} {r['end_value']:>14,.0f} "
            f"{r['total_return'] * 100:>9.2f}% {ann_label}"
        )

    timing = results[1]
    print(
        f"\n方案1 详情: 交易次数 {timing['n_trades']}, 末态持仓={timing['final_holding']}"
    )
    print("\n说明:")
    print("  - 基线/方案1 资金一次性投入,年化 = (1+total_return)^(1/years)-1")
    print("  - 方案2 资金分 149 月逐月投入,年化用 XIRR(平均工作时长 ~ 一半周期)")


if __name__ == "__main__":
    main()
