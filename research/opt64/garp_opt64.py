"""GARP v5: 完整PIT + 完整成本 + 币种修正.

修复:
1. PE币种: EPS(CNY)×1.1→HKD
2. 滑点 0.2%, 卖出税 0.1%, 最低佣金5元
3. MA90用PIT分红调整价 (f(t,d)=div_factor(t)/div_factor(d))
4. Turnover用真实价
"""

import pandas as pd
import numpy as np
import os
import sys
import math

BASE = os.path.expanduser("~/workspace/港股回测")
sys.path.insert(0, os.path.join(BASE, "code"))
from engine_pit_v2 import run_backtest, CNY_TO_HKD

PIT_PRICES = os.path.join(BASE, "data/processed/std_v1/prices_pit.parquet")
PRICES_ALL = os.path.join(BASE, "data/processed/std_v1/prices_all.parquet")
FIN_STD = os.path.join(BASE, "data/processed/std_v1/fin_annual_only.parquet")
IND = os.path.join(BASE, "data/processed/industry_user_v1.parquet")
EM_PATH = os.path.join(BASE, "data/raw/all_20150101-20260930_v1.parquet")

TOP_N = 12


def first_trading_days(dates):
    out = []
    for y in range(2015, 2027):
        for m in (4, 7, 10):
            cands = dates[(dates.year == y) & (dates.month == m)]
            if len(cands):
                out.append(cands[0])
    return sorted(out)


def main():
    print("加载...", flush=True)
    pit = pd.read_parquet(PIT_PRICES)
    pit["date"] = pd.to_datetime(pit["date"])
    close_traded = pit.pivot(index="date", columns="ticker", values="close_traded").astype(np.float32)
    open_traded = pit.pivot(index="date", columns="ticker", values="open_traded").astype(np.float32)
    vol = pit.pivot(index="date", columns="ticker", values="volume").astype(np.float32)
    # pit 保留给 run_backtest 用, 不删除

    pa = pd.read_parquet(PRICES_ALL)
    pa["date"] = pd.to_datetime(pa["date"])
    div_factor = pa.pivot(index="date", columns="ticker", values="div_factor").astype(np.float32)
    # close_adj 用于动量: 转float32省内存; 6月(126交易日)收益率, PIT干净
    close_adj = pa.pivot(index="date", columns="ticker", values="close_adj").astype(np.float32)
    mom6 = close_adj.pct_change(126)  # 过去126交易日总收益
    mom1 = close_adj.pct_change(21)  # 过去21交易日(1个月)总收益, PIT干净
    del pa
    import gc; gc.collect()

    em = pd.read_parquet(EM_PATH, columns=["ticker", "date", "close_raw"])
    em["date"] = pd.to_datetime(em["date"])
    close_raw26 = em.pivot(index="date", columns="ticker", values="close_raw").astype(np.float32)
    del em; gc.collect()

    fin = pd.read_parquet(FIN_STD)
    fin["report_date"] = pd.to_datetime(fin["report_date"])
    fin["visible_date"] = fin["report_date"] + pd.Timedelta(days=90)
    ind = pd.read_parquet(IND).set_index("ticker")["industry"]

    dates = close_traded.index.sort_values()
    # Turnover (真实价, PIT)
    turnover = close_traded * vol
    turn60 = turnover.rolling(60, min_periods=60).mean()

    fin_by_tic = {tic: g for tic, g in fin.groupby("ticker", sort=False)}
    sig_dates = first_trading_days(dates)
    print(f"{len(sig_dates)} 个信号日", flush=True)

    signals = {}
    for d in sig_dates:
        ds = d.strftime("%Y-%m-%d")
        # 可见年报
        rows = []
        for tic, g in fin_by_tic.items():
            sub = g[g["visible_date"] <= d]
            if len(sub) == 0:
                continue
            last = sub.sort_values("report_date").iloc[-1]
            rows.append((tic, last["eps_adj"], last["net_profit"], last["revenue"],
                        last["roe"], last["bps_adj"]))
        fdf = pd.DataFrame(rows, columns=["ticker", "eps_adj", "np", "rev", "roe", "bps"])
        fdf = fdf.set_index("ticker")
        # PE = close_raw26(HKD) / (eps_adj(CNY) * 1.1)
        # 未来因子抵消, PIT干净
        if d not in close_raw26.index:
            continue
        cr = close_raw26.loc[d]
        common = fdf.index.intersection(cr.index)
        # 币种换算: EPS从CNY到HKD
        eps_hkd = fdf.loc[common, "eps_adj"] * CNY_TO_HKD
        pe = cr.loc[common] / eps_hkd
        pe = pe.replace([np.inf, -np.inf], np.nan).dropna()
        pe = pe[(pe > 0) & (pe <= 12)]

        # CAGR (要求6个连续年报, 剔除极端值)
        cagr_np, cagr_rev = {}, {}
        for tic, g in fin_by_tic.items():
            sub = g[g["visible_date"] <= d].sort_values("report_date")
            if len(sub) < 6:
                continue
            seg = sub.tail(6)
            # 检查连续: 年份差应为5 (6个点, 5年间隔)
            years = seg["report_date"].dt.year.values
            if not all(np.diff(years) == 1):
                continue
            np0, np5 = seg["net_profit"].iloc[-1], seg["net_profit"].iloc[0]
            rv0, rv5 = seg["revenue"].iloc[-1], seg["revenue"].iloc[0]
            if pd.isna(np0) or pd.isna(np5) or np0 <= 0 or np5 <= 0:
                continue
            if pd.isna(rv0) or pd.isna(rv5) or rv0 <= 0 or rv5 <= 0:
                continue
            # 剔除极端CAGR (>200% 或 <-50% 可能是数据错误)
            cn = (np0 / np5) ** 0.2 - 1
            cr_ = (rv0 / rv5) ** 0.2 - 1
            if abs(cn) > 2.0 or abs(cr_) > 2.0:
                continue
            cagr_np[tic] = cn
            cagr_rev[tic] = cr_

        cands = set(pe.index)
        cands = {t for t in cands if t in cagr_np and cagr_np[t] >= 0.15}
        cands = {t for t in cands if t in cagr_rev and cagr_rev[t] >= 0.10}
        fdf_d = fdf.loc[fdf.index.intersection(cands)]
        # ROE: >=10% 且 <1000% (剔除极端值)
        cands = {t for t in cands if t in fdf_d.index and 10.0 <= fdf_d.loc[t, "roe"] < 1000.0}
        cands = {t for t in cands if t in fdf_d.index and fdf_d.loc[t, "bps"] > 0}

        # MA90 (PIT分红调整): P_adj(t,d) = close_traded(t) * div_factor(t)/div_factor(d)
        if d in dates:
            # 取过去90天
            d_idx = dates.get_loc(d)
            if d_idx >= 89:
                window = dates[d_idx-89:d_idx+1]
                # div_factor
                df_d = div_factor.loc[d]  # Series by ticker
                ma_vals = {}
                for tic in list(cands):  # 全量, 不限制
                    if tic not in close_traded.columns:
                        continue
                    try:
                        p_win = close_traded.loc[window, tic]
                        f_win = div_factor.loc[window, tic]
                        f_d = df_d[tic]
                        if pd.isna(f_d) or f_d == 0:
                            continue
                        p_adj = p_win * f_win / f_d
                        ma = p_adj.mean()
                        cur = close_traded.loc[d, tic]
                        if pd.notna(ma) and pd.notna(cur) and cur > ma:
                            ma_vals[tic] = True
                    except:
                        pass
                cands = {t for t in cands if t in ma_vals}

        # Turnover
        if d in turn60.index:
            tr = turn60.loc[d]
            cands = {t for t in cands if t in tr.index and pd.notna(tr[t]) and tr[t] >= 10_000_000}
        # 双动量过滤: 过去6个月>20% 且 过去1个月>0 (预计算mom6/mom1, PIT干净)
        if d in mom6.index:
            m = mom6.loc[d].dropna()
            cands = {t for t in cands if t in m.index and m[t] > 0.20}
        if d in mom1.index:
            m1 = mom1.loc[d].dropna()
            cands = {t for t in cands if t in m1.index and m1[t] > 0}
        cands = {t for t in cands if t in ind.index and pd.notna(ind[t])}
        # PEG (GARP筛选保留, 仅做过滤不排序)
        peg = {}
        for t in cands:
            if cagr_np[t] > 0:
                p = pe[t] / (cagr_np[t] * 100)
                if p <= 1.5:
                    peg[t] = p
        # 按6个月动量强度降序排序取前12 (代替PEG升序)
        mom_s = pd.Series({t: m[t] for t in peg.keys() if t in m.index}).sort_values(ascending=False)
        selected, cnt = [], {}
        for tic in mom_s.index:
            ii = ind[tic]
            if cnt.get(ii, 0) >= 2:
                continue
            cnt[ii] = cnt.get(ii, 0) + 1
            selected.append(tic)
            if len(selected) >= TOP_N:
                break
        signals[d] = selected
        print(f"  {ds}: {len(selected)}只", flush=True)

    print("\n回测...", flush=True)
    res = run_backtest(signals, pit)
    v = res.set_index("date")["value"]
    n_days = (v.index[-1] - v.index[0]).days
    cagr = (v.iloc[-1] / v.iloc[0]) ** (365.25 / n_days) - 1
    rp = v.pct_change().fillna(0)
    sharpe = float(rp.mean() / rp.std() * np.sqrt(252)) if rp.std() > 0 else 0
    dd = float((v / v.cummax() - 1).min())
    print(f"\n=== opt64 PE≤12 ===", flush=True)
    print(f"CAGR: {cagr:.2%}, Sharpe: {sharpe:.2f}, MDD: {dd:.2%}", flush=True)
    outdir = os.path.join(BASE, "results/runs/20261002_garp_opt64")
    os.makedirs(outdir, exist_ok=True)
    res.to_parquet(os.path.join(outdir, "equity.parquet"), index=False)
    import json
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump({"cagr": cagr, "sharpe": sharpe, "mdd": dd,
                   "change": "stricter PE<=12"}, f, indent=2)
    print(f"已存: {outdir}", flush=True)


if __name__ == "__main__":
    main()
