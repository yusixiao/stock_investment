"""三层回测引擎 v2: 完整成本 + 币种修正.

- 滑点: 买入价×(1+0.2%), 卖出价×(1-0.2%)
- 佣金: 0.03%, 最低5港币 (单边)
- 卖出税: 0.1%
- 币种: EPS(CNY)→HKD, 系数 CNY_HKD=1.1 (可配置)
"""

import pandas as pd
import numpy as np
import os
import math

BASE = os.path.expanduser("~/workspace/港股回测")
EM_PATH = os.path.join(BASE, "data/raw/all_20150101-20260930_v1.parquet")

# 成本参数 (对齐用户 broker.py)
SLIPPAGE = 0.002
COMMISSION_RATE = 0.0003
COMMISSION_MIN = 5.0
SELL_TAX = 0.001
# 币种: 1 CNY = 1.1 HKD (近似, 2015-2026均值)
CNY_TO_HKD = 1.1


class Portfolio:
    def __init__(self, cash=1_000_000.0):
        self.cash = cash
        self.holdings = {}
        em = pd.read_parquet(EM_PATH, columns=["ticker", "date", "splits", "dividends"])
        em["date"] = pd.to_datetime(em["date"])
        em["ds"] = em["date"].dt.strftime("%Y-%m-%d")
        self.splits = {}
        self.divs = {}
        for _, r in em[em["splits"].notna() & (em["splits"] != 0)].iterrows():
            self.splits.setdefault(r["ticker"], {})[r["ds"]] = float(r["splits"])
        for _, r in em[em["dividends"].notna() & (em["dividends"] != 0)].iterrows():
            d = self.divs.setdefault(r["ticker"], {})
            d[r["ds"]] = d.get(r["ds"], 0) + float(r["dividends"])
        # 分红税率 (用户定: 10%)
        self.div_tax = 0.10

    def apply_corporate_actions(self, date_str):
        for tic, shares in list(self.holdings.items()):
            if shares == 0:
                continue
            if tic in self.splits and date_str in self.splits[tic]:
                ratio = self.splits[tic][date_str]
                self.holdings[tic] = int(shares * ratio)
            if tic in self.divs and date_str in self.divs[tic]:
                div_ps = self.divs[tic][date_str]
                # 分红是港币 (Eastmoney), 直接加
                self.cash += shares * div_ps * (1 - self.div_tax)

    def market_value(self, price_map):
        mv = self.cash
        for tic, shares in self.holdings.items():
            if tic in price_map and shares > 0:
                mv += shares * price_map[tic]
        return mv


def commission(amount):
    """单边佣金, 最低5元."""
    return max(amount * COMMISSION_RATE, COMMISSION_MIN) if amount > 0 else 0.0


def run_backtest(signals, price_pit):
    """signals: {signal_date: [tickers]}.
    price_pit: DataFrame with ticker, date, open_traded, close_traded.
    执行价: (open+close)/2 × (1±滑点).
    """
    price_pit["date"] = pd.to_datetime(price_pit["date"])
    # 中间价
    price_pit["mid"] = (price_pit["open_traded"] + price_pit["close_traded"]) / 2
    mid_px = price_pit.pivot(index="date", columns="ticker", values="mid")
    close_px = price_pit.pivot(index="date", columns="ticker", values="close_traded")

    dates = mid_px.index.sort_values()
    dates_list = list(dates)
    pf = Portfolio()

    exec_map = {}
    for sd in sorted(signals.keys()):
        sd = pd.Timestamp(sd)
        if sd in dates:
            i = dates_list.index(sd)
            if i + 1 < len(dates_list):
                exec_map[dates_list[i + 1]] = sd

    values = []
    for d in dates_list:
        ds = d.strftime("%Y-%m-%d")
        pf.apply_corporate_actions(ds)
        if d in exec_map:
            sd = exec_map[d]
            targets = signals[sd]
            pmap = close_px.loc[d].to_dict()
            V = pf.market_value(pmap)
            # 卖出非目标
            for tic in list(pf.holdings.keys()):
                if tic not in targets and pf.holdings[tic] > 0:
                    mid = mid_px.loc[d, tic] if tic in mid_px.columns else np.nan
                    if pd.notna(mid) and mid > 0:
                        sell_price = mid * (1 - SLIPPAGE)
                        proceeds = pf.holdings[tic] * sell_price
                        cost = commission(proceeds) + proceeds * SELL_TAX
                        pf.cash += proceeds - cost
                        pf.holdings[tic] = 0
            # 买入到等权
            N = len(targets)
            if N > 0:
                tv = V / N
                for tic in targets:
                    if tic not in mid_px.columns:
                        continue
                    mid = mid_px.loc[d, tic]
                    if pd.isna(mid) or mid <= 0:
                        continue
                    buy_price = mid * (1 + SLIPPAGE)
                    cur = pf.holdings.get(tic, 0)
                    tgt_sh = math.floor(tv / buy_price / 100) * 100
                    diff = tgt_sh - cur
                    if diff > 0:
                        gross = diff * buy_price
                        cost = commission(gross)
                        total = gross + cost
                        if total <= pf.cash:
                            pf.cash -= total
                            pf.holdings[tic] = tgt_sh
                    elif diff < 0:
                        # 卖出部分
                        sell_price = mid * (1 - SLIPPAGE)
                        proceeds = (-diff) * sell_price
                        cost = commission(proceeds) + proceeds * SELL_TAX
                        pf.cash += proceeds - cost
                        pf.holdings[tic] = tgt_sh
        pmap = close_px.loc[d].to_dict()
        values.append((d, pf.market_value(pmap)))
    return pd.DataFrame(values, columns=["date", "value"])
