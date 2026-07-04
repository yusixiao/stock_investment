#!/usr/bin/env python3
"""林奇多腿组合 · 共享单账户真回测 (Exp-3) —— 最终可部署数字。

见 ``lynch_meta_combo_strategy.py`` 头注:用 ``LynchMetaComboStrategy`` 把推荐组合 slow40
(slow_growers .40 / turnarounds .30 / asset_plays .30)合入**单一回测账户**真跑,
对每个窗口 × 每种 ``rebalance_mode`` 各跑一次, 并与 Exp-2 的**净值层曲线混合估计**对照。

对照口径(关键)
----------------
- Exp-2 估计: 直接读 Exp-2 缓存的各腿逐日收益 ``legs_daily_returns_{window}.parquet``,
  用同一 ``_combo_daily`` 按 slow40 权重月度再平衡合成 → ``_metrics``。**无成本/无现金约束**。
- Exp-3 真回测: 单账户 ``BacktestEngine.run()`` 的逐日净值 → 同一 ``_metrics``。含真实成本。
- 两者用**完全相同**的 ``_metrics``(CAGR/年化波动/MaxDD/Sharpe rf=0), 直接可比。
  差额 = Exp-2 忽略的现实摩擦(再平衡换手成本 / 现金竞争 / 整手 / 重叠净额)。

用法(长任务, 后台跑)
  nohup python backend/services/backtest/strategies/experiments/lynch/portfolio/run_portfolio_shared_pool.py \
      > logs/lynch_portfolio_shared_pool.log 2>&1 &
"""
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
log = logging.getLogger("lynch_pf_pool")

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
from services.backtest.strategies.experiments.lynch.portfolio.lynch_meta_combo_strategy import (
    LynchMetaComboStrategy,
)

CSI300_CODE = "CSI300"
OUT_DIR = Path(__file__).resolve().parent
TRADING_DAYS = 252
INITIAL_CAPITAL = 1_000_000

# 3 腿 champion 配置(与 Exp-1 / Exp-2 逐字一致)
LEG_CONFIGS = [
    ("slow_growers", LynchSlowGrowersStrategy,
     {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12,
      "max_per_sector": 2, "rebalance_months": [6]}),
    ("turnarounds", LynchTurnaroundsStrategy,
     {"rebalance_months": [3, 6, 9, 12], "top_n": 10, "max_debt_ratio": 0.60}),
    ("asset_plays", LynchAssetPlaysStrategy,
     {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
      "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 150}),
]
# 推荐组合 slow40_3legs(权重顺序对齐 Exp-2 parquet 列序 slow/turn/asset/fast)
WEIGHTS = {"slow_growers": 0.40, "turnarounds": 0.30, "asset_plays": 0.30}
LEG_NAMES_4 = ["slow_growers", "turnarounds", "asset_plays", "fast_growers"]
W_VEC_4 = np.array([0.40, 0.30, 0.30, 0.0])  # slow40

MODES = ["monthly", "on_change"]
WINDOWS = {
    "since2016": ("2016-01-01", "2026-06-01"),  # 主
    "full": ("2010-01-01", "2026-06-01"),       # 辅
}


def _metrics(daily: pd.Series) -> dict:
    """从日度收益序列算 CAGR / 年化波动 / MaxDD / Sharpe(rf=0)。与 Exp-2 逐字一致。"""
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
    """按目标权重 w 月度再平衡合成组合日度收益。与 Exp-2 逐字一致(净值层估计)。"""
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


def _run_pool(sliced, mode: str) -> tuple[dict, pd.Series]:
    """单账户真回测一次。返回 (指标 dict, 逐日收益 Series)。"""
    # 每次新建子策略实例, 避免跨窗口/跨 mode 的内部状态污染
    legs = [(name, cls(param_overrides=ov)) for name, cls, ov in LEG_CONFIGS]
    meta = LynchMetaComboStrategy(legs=legs, weights=WEIGHTS, rebalance_mode=mode)
    engine = BacktestEngine(
        strategy=meta,
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
    ec = res.get("equity_curve") or []
    if not ec:
        return {"cagr": None, "n_days": 0}, pd.Series(dtype=float)
    dates = pd.to_datetime([p["date"] for p in ec])
    vals = pd.Series([float(p["total_value"]) for p in ec], index=dates).sort_index()
    daily = vals.pct_change().dropna()

    raw = res.get("raw_trades", []) or []
    n_tr = len(raw)
    buy_val = sum(float(t["shares"]) * float(t["price"])
                  for t in raw if t.get("direction") == "buy")
    sell_val = sum(float(t["shares"]) * float(t["price"])
                   for t in raw if t.get("direction") == "sell")
    cost = sum(float(t.get("commission", 0)) + float(t.get("tax", 0)) for t in raw)
    final_val = float(vals.iloc[-1])
    avg_eq = float(vals.mean())
    years = max((vals.index[-1] - vals.index[0]).days, 1) / 365.25
    turnover_ann = ((buy_val + sell_val) / 2.0 / avg_eq / years) if avg_eq > 0 else None

    m = _metrics(daily)
    m.update({
        "engine_metrics": res.get("metrics", {}),
        "n_trades": n_tr,
        "buy_value": round(buy_val, 2),
        "sell_value": round(sell_val, 2),
        "total_cost": round(cost, 2),
        "cost_pct_of_final": (cost / final_val) if final_val else None,
        "final_value": round(final_val, 2),
        "turnover_ann": turnover_ann,
    })
    return m, daily


def _pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs",
             len(bundle.stock_data), time.time() - t0)

    report = {}
    for wname, (start, end) in WINDOWS.items():
        log.info("==== window %s (%s → %s) ====", wname, start, end)
        sliced = data_cache.slice_bundle(bundle, None, start, end)

        blk = {"window": [start, end], "weights": WEIGHTS, "modes": {}}

        # 1) Exp-2 净值层估计(读缓存 parquet, 无则跳过)
        pq = OUT_DIR / f"legs_daily_returns_{wname}.parquet"
        if pq.exists():
            R = pd.read_parquet(pq)[LEG_NAMES_4]
            est = _metrics(_combo_daily(R, W_VEC_4))
            blk["exp2_estimate"] = est
            log.info("[%s] Exp-2 估计 slow40: CAGR=%s Sharpe=%.2f",
                     wname, _pct(est.get("cagr")), est.get("sharpe") or 0)
        else:
            log.warning("[%s] 缺 %s, 跳过 Exp-2 估计", wname, pq.name)

        # 2) Exp-3 单账户真回测 × 各 mode
        for mode in MODES:
            t1 = time.time()
            m, _ = _run_pool(sliced, mode)
            blk["modes"][mode] = m
            log.info("[%s/%s] %.1fs trades=%s turnover=%.2f CAGR=%s Sharpe=%.2f cost=%s",
                     wname, mode, time.time() - t1, m.get("n_trades"),
                     m.get("turnover_ann") or 0, _pct(m.get("cagr")),
                     m.get("sharpe") or 0, _pct(m.get("cost_pct_of_final")))

        # 3) 基准
        bench = _csi300_daily_returns(start, end)
        if bench is not None:
            blk["csi300"] = _metrics(bench)

        report[wname] = blk
        _write_overview(report)

    (OUT_DIR / "portfolio_shared_pool.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    log.info("ALL DONE -> portfolio_shared_pool.json + portfolio_shared_pool_overview.md")


def _write_overview(report):
    lines = [
        "# 林奇多腿组合 · 共享单账户真回测 (Exp-3)",
        "",
        "> 推荐组合 **slow40**: slow_growers 0.40 / turnarounds 0.30 / asset_plays 0.30。",
        "> **Exp-3 = 单账户真回测**(一份现金 + 整手 + T+1 + 佣金万3 + 印花税千1 + 滑点 + 重叠净额)。",
        "> **Exp-2 估计 = 各腿满仓净值曲线按月度再平衡加权混合**(无成本 / 无现金约束, 乐观上界)。",
        "> 两者用同一 `_metrics`(CAGR/年化波动/MaxDD/Sharpe rf=0)直接可比; 差额 = 现实摩擦成本。",
        "> `monthly` = 每月重置到目标权重(换手最高); `on_change` = 仅腿调仓时才动(换手最低)。",
        "",
    ]
    for wname, blk in report.items():
        s, e = blk["window"]
        lines += [f"## 窗口 `{wname}` ({s} → {e})", "",
                  "| 口径 | CAGR | 年化波动 | MaxDD | Sharpe | 笔数 | 年化换手 | 成本/终值 |",
                  "|---|---|---|---|---|---|---|---|"]
        est = blk.get("exp2_estimate")
        if est:
            lines.append(f"| Exp-2 估计(乐观) | {_pct(est.get('cagr'))} | "
                         f"{_pct(est.get('ann_vol'))} | {_pct(est.get('max_drawdown'))} | "
                         f"{(est.get('sharpe') or 0):.2f} | - | - | - |")
        for mode in MODES:
            m = blk["modes"].get(mode, {})
            if not m:
                continue
            lines.append(f"| Exp-3 {mode} | {_pct(m.get('cagr'))} | "
                         f"{_pct(m.get('ann_vol'))} | {_pct(m.get('max_drawdown'))} | "
                         f"{(m.get('sharpe') or 0):.2f} | {m.get('n_trades', '-')} | "
                         f"{(m.get('turnover_ann') or 0):.2f} | "
                         f"{_pct(m.get('cost_pct_of_final'))} |")
        bench = blk.get("csi300")
        if bench:
            lines.append(f"| CSI300(基准) | {_pct(bench.get('cagr'))} | "
                         f"{_pct(bench.get('ann_vol'))} | {_pct(bench.get('max_drawdown'))} | "
                         f"{(bench.get('sharpe') or 0):.2f} | - | - | - |")
        lines.append("")

    (OUT_DIR / "portfolio_shared_pool_overview.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
