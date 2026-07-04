"""子区间审计: 量化 40/30/30 组合的 CAGR 里 2010-2015 早期小样本的占比。

动机(用户 2026-07-04 提出的一致性质疑):
  单型报告《林奇六类型策略研究报告.md》§7 明确认定 —— 隐蔽资产腿全期 14.73% "几乎全部来自
  2010-2015 那 12 笔"(该段年化 26.9%, 样本统计无意义), 机会集充实后的诚实值(2016+)仅 8.38%,
  并把它与"周期型 11.11% 是 2015 泡沫幻象"归为同一种过拟合。
  组合报告改用 full-only 口径后, 采用了 14.73%(= 单型报告弃用的那个数)。本脚本量化: 组合的
  full CAGR 里有多少来自 2010-2015 早期小样本, 用数据决定组合报告该用哪个口径。

做法:
  读 legs_daily_returns_full.parquet(各腿 standalone 日度收益, 已含成本), 逐字复用
  run_portfolio_weights 的 _metrics / _combo_daily(月度再平衡), 在三段窗口上分别算
  每条腿 + 40/30/30 核心三腿组合的 CAGR/年化波动/MaxDD/Sharpe。无需重载 bundle, 秒级。
"""
import numpy as np
import pandas as pd
from pathlib import Path

TRADING_DAYS = 252
HERE = Path(__file__).resolve().parent
PQ = HERE / "legs_daily_returns_full.parquet"

LEG_COLS = ["slow_growers", "turnarounds", "asset_plays", "stalwarts"]
W_CORE = np.array([0.40, 0.30, 0.30, 0.00])  # slow/turn/asset/stalwarts, 推荐三腿

PERIODS = {
    "early (2010-2015)": ("2010-01-01", "2015-12-31"),
    "mature(2016-2026)": ("2016-01-01", "2026-06-01"),
    "full  (2010-2026)": ("2010-01-01", "2026-06-01"),
}


def _metrics(daily: pd.Series) -> dict:
    """逐字复制 run_portfolio_weights._metrics: 从日度收益算 CAGR/年化波动/MaxDD/Sharpe(rf=0)。"""
    daily = daily.dropna()
    if len(daily) < 20:
        return {"cagr": None, "ann_vol": None, "max_drawdown": None,
                "sharpe": None, "total_return": None, "n_days": len(daily)}
    eq = (1.0 + daily).cumprod()
    total = float(eq.iloc[-1] - 1.0)
    days = max((daily.index[-1] - daily.index[0]).days, 1)
    years = days / 365.25
    cagr = (1.0 + total) ** (1.0 / years) - 1.0 if (1.0 + total) > 0 else None
    sd = float(daily.std(ddof=1))
    ann_vol = sd * np.sqrt(TRADING_DAYS)
    sharpe = (float(daily.mean()) / sd * np.sqrt(TRADING_DAYS)) if sd > 1e-12 else None
    dd = eq / eq.cummax() - 1.0
    return {"cagr": cagr, "ann_vol": ann_vol, "max_drawdown": abs(float(dd.min())),
            "sharpe": sharpe, "total_return": total, "n_days": int(len(daily))}


def _combo_daily(R: pd.DataFrame, w: np.ndarray) -> pd.Series:
    """逐字复制 run_portfolio_weights._combo_daily: 按目标权重月度再平衡, 合成组合日度收益。"""
    Rv = R.values
    months = R.index.to_period("M")
    sleeves = w.astype(float).copy()
    out = np.empty(len(R))
    pv_prev = float(sleeves.sum())
    prev_m = None
    for t in range(len(R)):
        m = months[t]
        if prev_m is not None and m != prev_m:
            sleeves = w * float(sleeves.sum())
        sleeves = sleeves * (1.0 + Rv[t])
        pv = float(sleeves.sum())
        out[t] = pv / pv_prev - 1.0
        pv_prev = pv
        prev_m = m
    return pd.Series(out, index=R.index)


def _fmt(m: dict) -> str:
    if m["cagr"] is None:
        return f"  n_days={m['n_days']:>4}  (样本不足)"
    return (f"CAGR={m['cagr']*100:6.2f}%  vol={m['ann_vol']*100:5.2f}%  "
            f"MaxDD={m['max_drawdown']*100:5.2f}%  Sharpe={m['sharpe']:4.2f}  "
            f"总收益={m['total_return']*100:7.1f}%  n={m['n_days']}")


def main():
    df = pd.read_parquet(PQ)
    print(f"parquet: {df.shape[0]} 日 × {df.shape[1]} 腿  {df.index.min().date()} → {df.index.max().date()}\n")

    names = {"slow_growers": "缓慢增长", "turnarounds": "困境反转",
             "asset_plays": "隐蔽资产", "stalwarts": "稳健增长"}
    for pname, (s, e) in PERIODS.items():
        sub = df.loc[s:e]
        print(f"================ {pname}  ({sub.index.min().date()} → {sub.index.max().date()}, {len(sub)} 日) ================")
        for c in LEG_COLS:
            print(f"  [{names[c]:<4}] {_fmt(_metrics(sub[c]))}")
        combo = _combo_daily(sub, W_CORE)
        print(f"  [组合40/30/30] {_fmt(_metrics(combo))}")
        print()

    # 早期占比: 组合累计净值中, 2010-2015 段贡献了多少倍增长
    full = df.loc["2010-01-01":"2026-06-01"]
    early = df.loc["2010-01-01":"2015-12-31"]
    mature = df.loc["2016-01-01":"2026-06-01"]
    c_full = _metrics(_combo_daily(full, W_CORE))
    c_early = _metrics(_combo_daily(early, W_CORE))
    c_mature = _metrics(_combo_daily(mature, W_CORE))
    eq_full = 1.0 + c_full["total_return"]
    eq_early = 1.0 + c_early["total_return"]
    eq_mature = 1.0 + c_mature["total_return"]
    print("================ 组合早期小样本占比拆解 ================")
    print(f"  组合净值倍数: early(2010-15)={eq_early:.3f}×   mature(2016+)={eq_mature:.3f}×   full={eq_full:.3f}×")
    print(f"  验证 early×mature = {eq_early*eq_mature:.3f}  vs  full={eq_full:.3f}  (应近似相等)")
    print(f"  full CAGR {c_full['cagr']*100:.2f}%  vs  mature-only CAGR {c_mature['cagr']*100:.2f}%  "
          f"→ 早期段把组合全期 CAGR 抬高了 {(c_full['cagr']-c_mature['cagr'])*100:.2f}pp")
    # 隐蔽资产腿单独的早期 vs 成熟对比(印证单型报告 14.73% vs 8.38%)
    a_full = _metrics(full["asset_plays"])
    a_mature = _metrics(mature["asset_plays"])
    print(f"  [隐蔽资产腿] full CAGR {a_full['cagr']*100:.2f}%  vs  mature CAGR {a_mature['cagr']*100:.2f}%  "
          f"(单型报告口径: full 14.73% / 2016+ 8.38%)")


if __name__ == "__main__":
    main()
