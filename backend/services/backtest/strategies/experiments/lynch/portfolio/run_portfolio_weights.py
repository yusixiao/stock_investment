#!/usr/bin/env python3
"""林奇组合 · 权重搜索 (Exp-2) —— 求风险调整后最优的稳健组合。

前提(Exp-1 相关性闸门已通过, 全期修复后数据 2026-07-04):
- 核心三腿(主组合) = slow_growers / turnarounds / asset_plays: 全期年化 13.90/16.14/14.73%,
  互相关全 <0.5(slow×turn 0.33、turn×asset 0.42、slow×asset 0.46), 市场 beta 低(×CSI300 0.45~0.58),
  分散价值最强。
- 第 4 腿 = stalwarts(对照): INDUSTRY_NAME 修复后已恢复 11.24%(此前坏数据塌缩至 ~0 笔),
  与 turnarounds 相关 0.22(全场最低对) —— 但与 slow_growers 相关 0.59(高股息+质量+大盘价值重叠)、
  市场 beta 0.64 偏高, 收益低于核心三腿。故列为对照(*4 方案含它), 由数据决定是否值得纳入。
- fast_growers / cyclicals 已剔: 修复后全期仅 4.48/6.43%、市场 beta 0.68/0.81 近纯 beta, 组合无增量。

方法学:
- 各腿独立满仓回测取「逐日净值曲线」→ 日度简单收益率。
- 组合 = 按目标权重「月度再平衡」合成的日度收益序列(月初重置到目标权重, 月内自然漂移);
  这是策略-of-策略层的再平衡, 每腿收益已含各自交易成本, 此层不再计过度换手成本(月度足够低频)。
- 指标(CAGR / 年化波动 / MaxDD / Sharpe)一律从「组合日度收益」自算, 单腿也用同一函数重算,
  保证组合与单腿口径一致可比(与引擎日度指标略有出入属正常, 引擎值见 Exp-1)。
- 权重方案强调「稳健 / 非过拟合」: 等权 / 逆波动 / 最小方差; 「样本内最大 Sharpe」仅作
  过拟合上界参考(样本内最优 ≠ 样本外可得), 不作推荐。
- 窗口: 全期(2010-01 → 2026-06)单一口径(since2016 窗口已弃, 2026-07-04)。
  持久化各腿日度收益到 parquet, 便于日后免重跑迭代权重。

用法(长任务, 后台跑):
  nohup python backend/services/backtest/strategies/experiments/lynch/portfolio/run_portfolio_weights.py \
      > logs/lynch_portfolio_weights.log 2>&1 &
"""
import itertools
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("lynch_pf_weights")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.lynch_slow_growers.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_turnarounds.lynch_turnarounds_strategy import (
    LynchTurnaroundsStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_asset_plays.asset_plays_strategy import (
    LynchAssetPlaysStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_stalwarts.lynch_stalwarts_strategy import (
    LynchStalwartsStrategy,
)

CSI300_CODE = "CSI300"
OUT_DIR = Path(__file__).resolve().parent
TRADING_DAYS = 252

# 腿池(配置与 Exp-1 逐字一致, 来源见 run_portfolio_corr.py TYPES 注释)。
# 前 3 = 核心三腿(主组合); 第 4 = stalwarts(对照, *4 方案含它, *3legs 方案权重置 0)。
LEGS = [
    ("slow_growers", LynchSlowGrowersStrategy,
     {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12,
      "max_per_sector": 2, "rebalance_months": [6]}),
    ("turnarounds", LynchTurnaroundsStrategy,
     {"rebalance_months": [3, 6, 9, 12], "top_n": 10, "max_debt_ratio": 0.60}),
    ("asset_plays", LynchAssetPlaysStrategy,
     {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
      "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 150}),
    ("stalwarts", LynchStalwartsStrategy,
     {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
      "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0}),
]
LEG_NAMES = [n for n, _, _ in LEGS]

WINDOWS = {
    "full": ("2010-01-01", "2026-06-01"),  # 全期单一口径(since2016 窗口已弃, 2026-07-04)
}


def _run_daily_returns(strat_cls, overrides, sliced):
    """跑一腿完整回测, 返回逐日净值 → 日度简单收益率 Series(DatetimeIndex)。"""
    strat = strat_cls(param_overrides=overrides)
    engine = BacktestEngine(
        strategy=strat,
        stock_data=sliced.stock_data,
        valuation_data=sliced.valuation_data,
        dividend_data=sliced.dividend_data,
        financial_data=sliced.financial_data,
        balance_data=sliced.balance_data,
        cashflow_data=sliced.cashflow_data,
        income_data=sliced.income_data,
        weekly_data=sliced.weekly_data,
        monthly_data=sliced.monthly_data,
        iter_start=sliced.iter_start_idx,
        iter_end=sliced.iter_end_idx,
    )
    res = engine.run()
    ec = res.get("equity_curve")
    if not ec:
        return None, 0
    dates = pd.to_datetime([p["date"] for p in ec])
    vals = pd.Series([float(p["total_value"]) for p in ec], index=dates).sort_index()
    return vals.pct_change().dropna(), len(res.get("raw_trades", []))


def _csi300_daily_returns(start, end):
    try:
        from services.market_data.duckdb_store import get_store
        df = get_store().query_index("A", CSI300_CODE, start, end)
        if df is None or df.empty or "close" not in df.columns:
            return None
        s = pd.Series(df["close"].astype(float).values,
                      index=pd.to_datetime(df["date"])).sort_index()
        return s.pct_change().dropna()
    except Exception as e:
        log.warning("CSI300 daily returns failed: %s", e)
        return None


def _metrics(daily: pd.Series) -> dict:
    """从日度收益序列算 CAGR / 年化波动 / MaxDD / Sharpe(rf=0)。"""
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
    return {
        "cagr": cagr, "ann_vol": ann_vol, "max_drawdown": abs(float(dd.min())),
        "sharpe": sharpe, "total_return": total, "n_days": int(len(daily)),
    }


def _combo_daily(R: pd.DataFrame, w: np.ndarray) -> pd.Series:
    """按目标权重 w 月度再平衡, 合成组合日度收益序列。

    月初(月份变更首日)将各腿仓位重置回目标权重 * 当前总市值; 月内各腿按自身收益自然漂移。
    """
    Rv = R.values
    months = R.index.to_period("M")
    sleeves = w.astype(float).copy()  # 初始总市值=sum(w)=1
    out = np.empty(len(R))
    pv_prev = float(sleeves.sum())
    prev_m = None
    for t in range(len(R)):
        m = months[t]
        if prev_m is not None and m != prev_m:      # 跨月 → 再平衡(不改变总市值)
            sleeves = w * float(sleeves.sum())
        sleeves = sleeves * (1.0 + Rv[t])           # 当日各腿收益
        pv = float(sleeves.sum())
        out[t] = pv / pv_prev - 1.0
        pv_prev = pv
        prev_m = m
    return pd.Series(out, index=R.index)


def _grid_weights(n: int, step: float = 0.05):
    """生成 n 资产、步长 step、和为 1 的所有权重组合。"""
    k = int(round(1.0 / step))
    for parts in itertools.product(range(k + 1), repeat=n):
        if sum(parts) == k:
            yield np.array(parts, dtype=float) * step


def _search(R: pd.DataFrame, objective: str, drop: str = None) -> np.ndarray:
    """网格搜索: objective in {max_sharpe, min_var}。用日度加权代理(R@w)快速评估。

    drop=腿名 → 该腿强制权重 0, 只在其余腿上搜索(用于核心三腿最优)。
    返回全长(=R 列数)权重向量, 被 drop 的腿位置为 0。
    """
    cols = list(R.columns)
    active = [i for i, c in enumerate(cols) if c != drop]
    Rv = R.values
    best_w, best_score = None, None
    with np.errstate(all="ignore"):
        for wsub in _grid_weights(len(active), step=0.05):
            w = np.zeros(len(cols))
            w[active] = wsub
            pr = Rv @ w
            sd = pr.std(ddof=1)
            if objective == "max_sharpe":
                score = (pr.mean() / sd) if sd > 1e-12 else -1e9
            else:  # min_var
                score = -sd
            if best_score is None or score > best_score:
                best_score, best_w = score, w
    return best_w


def _named_schemes(R: pd.DataFrame) -> dict:
    """构造权重方案(部分依赖窗口内数据: 逆波动)。顺序 = LEG_NAMES。

    命名约定: `*4` = 含 stalwarts 的 4 腿对照; `*3_core`/`*3legs` = 核心三腿
    (slow/turn/asset, stalwarts 权重=0)= 主组合。
    """
    vol = R.std(ddof=1).values  # 各腿日度波动
    inv = 1.0 / np.where(vol > 0, vol, np.inf)
    inv_vol4 = inv / inv.sum()
    # 核心三腿(去 stalwarts)逆波动
    inv3 = inv.copy(); inv3[LEG_NAMES.index("stalwarts")] = 0.0
    inv_vol3 = inv3 / inv3.sum()

    schemes = {
        # 4 腿(含 stalwarts 对照)
        "equal4": np.array([0.25, 0.25, 0.25, 0.25]),
        "inv_vol4": inv_vol4,
        "min_var4": _search(R, "min_var"),
        "max_sharpe4_OVERFIT": _search(R, "max_sharpe"),
        # 核心三腿(slow/turn/asset, stalwarts=0)—— 主组合
        "equal3_core": np.array([1 / 3, 1 / 3, 1 / 3, 0.0]),
        "inv_vol3_core": inv_vol3,
        "min_var3_core": _search(R, "min_var", drop="stalwarts"),
        "slow40_3legs": np.array([0.40, 0.30, 0.30, 0.0]),
        "slow50_3legs": np.array([0.50, 0.25, 0.25, 0.0]),
        "slow_only_ref": np.array([1.0, 0.0, 0.0, 0.0]),
    }
    return schemes


ROBUST = {"equal4", "inv_vol4", "min_var4", "equal3_core", "inv_vol3_core",
          "min_var3_core", "slow40_3legs", "slow50_3legs"}


def _pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def _wstr(w):
    return "/".join(f"{v:.2f}" for v in w)


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)

    report = {}
    for wname, (start, end) in WINDOWS.items():
        log.info("==== window %s (%s → %s) ====", wname, start, end)
        sliced = data_cache.slice_bundle(bundle, None, start, end)

        # 1) 各腿日度收益
        series, trades = {}, {}
        for name, cls, ov in LEGS:
            t1 = time.time()
            dr, ntr = _run_daily_returns(cls, ov, sliced)
            if dr is not None and not dr.empty:
                series[name] = dr
                trades[name] = ntr
            log.info("[%s/%s] %.1fs trades=%d days=%d",
                     wname, name, time.time() - t1, ntr, 0 if dr is None else len(dr))

        R = pd.DataFrame(series).dropna(how="any")
        R = R[LEG_NAMES]  # 固定列序
        R.to_parquet(OUT_DIR / f"legs_daily_returns_{wname}.parquet")
        log.info("[%s] aligned R shape=%s", wname, R.shape)

        bench = _csi300_daily_returns(start, end)

        # 2) 单腿指标(自算, 与组合同口径)
        legs_metrics = {n: _metrics(R[n]) for n in LEG_NAMES}
        if bench is not None:
            legs_metrics["CSI300"] = _metrics(bench)

        # 3) 权重方案 → 组合指标(月度再平衡)
        schemes = _named_schemes(R)
        scheme_rows = {}
        for sname, w in schemes.items():
            cr = _combo_daily(R, np.asarray(w, dtype=float))
            m = _metrics(cr)
            m["weights"] = {LEG_NAMES[i]: round(float(w[i]), 4) for i in range(len(LEG_NAMES))}
            m["robust"] = sname in ROBUST
            scheme_rows[sname] = m

        report[wname] = {
            "window": [start, end],
            "n_days": int(R.shape[0]),
            "trades": trades,
            "legs_metrics": legs_metrics,
            "schemes": scheme_rows,
        }
        _write_overview(report)

    (OUT_DIR / "portfolio_weights.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    log.info("ALL DONE -> portfolio_weights.json + portfolio_weights_overview.md")


def _write_overview(report):
    lines = [
        "# 林奇组合 · 权重搜索 (Exp-2)",
        "",
        "> 核心三腿(主组合) = slow_growers / turnarounds / asset_plays;第 4 腿 = stalwarts(对照)。",
        "> `*4` 方案含 stalwarts;`*3_core`/`*3legs` 方案 stalwarts 权重=0 即核心三腿。fast/cyclicals 已剔。",
        "> 所有指标从「日度收益」自算(CAGR/年化波动/MaxDD/Sharpe rf=0), 单腿与组合同口径可比。",
        "> 组合 = 目标权重「月度再平衡」合成; `*_OVERFIT` 为样本内最优, 仅作上界参考, **不推荐**。",
        "> 权重顺序 = slow_growers/turnarounds/asset_plays/stalwarts。",
        "",
    ]
    for wname, blk in report.items():
        lines += [f"## 窗口 `{wname}` (n={blk['n_days']} 日)", ""]
        lines += ["### 单腿(自算日度口径)", "",
                  "| 腿 | 笔数 | CAGR | 年化波动 | MaxDD | Sharpe |",
                  "|---|---|---|---|---|---|"]
        for n in LEG_NAMES:
            m = blk["legs_metrics"].get(n, {})
            lines.append(f"| {n} | {blk['trades'].get(n, '-')} | {_pct(m.get('cagr'))} | "
                         f"{_pct(m.get('ann_vol'))} | {_pct(m.get('max_drawdown'))} | "
                         f"{(m.get('sharpe') or 0):.2f} |")
        if "CSI300" in blk["legs_metrics"]:
            m = blk["legs_metrics"]["CSI300"]
            lines.append(f"| CSI300(基准) | - | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'))} | "
                         f"{_pct(m.get('max_drawdown'))} | {(m.get('sharpe') or 0):.2f} |")
        lines.append("")

        # 组合方案按 Sharpe 降序
        rows = sorted(blk["schemes"].items(),
                      key=lambda kv: (kv[1].get("sharpe") or -9), reverse=True)
        lines += ["### 组合权重方案(按 Sharpe 降序)", "",
                  "| 方案 | 稳健 | 权重(slow/turn/asset/stalwarts) | CAGR | 年化波动 | MaxDD | Sharpe |",
                  "|---|---|---|---|---|---|---|"]
        for sname, m in rows:
            w = m["weights"]
            wv = [w[n] for n in LEG_NAMES]
            flag = "✓" if m.get("robust") else "⚠上界"
            lines.append(f"| {sname} | {flag} | {_wstr(wv)} | {_pct(m.get('cagr'))} | "
                         f"{_pct(m.get('ann_vol'))} | {_pct(m.get('max_drawdown'))} | "
                         f"{(m.get('sharpe') or 0):.2f} |")
        lines.append("")

    (OUT_DIR / "portfolio_weights_overview.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
