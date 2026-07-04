#!/usr/bin/env python3
"""林奇组合 · 2016+ 最优组合的单账户真回测 (Exp-4 的 Exp-3 补充)。

缘起
----
run_portfolio_2016plus.py (Exp-4) 的曲线级搜索结论:诚实的 2016+ 窗口里,
**没有任何稳健组合能双反超缓慢增长单打**(slow-alone 14.11% / Sharpe 0.92);
唯一在 Sharpe 上险胜 0.01 的稳健组合是 **min_var3 = slow .70 / turn .10 / asset .20**
(曲线级 13.49% / Sharpe 0.93), 但以让渡 0.62pp 收益换取。

曲线级估计忽略现实摩擦(整手 / 单一现金池 / 佣金印花税滑点 / 跨腿重叠净额),
§8 已证真单账户通常比曲线级低 ~0.5pp 且回撤更深。故对这个「2016+ 最优稳健组合」
补一次**真单账户回测**, 看它含成本后能否守住相对缓慢增长单打的那 0.01 Sharpe 优势。
预期: 摩擦会抹掉这道发丝级优势 → 坐实「成熟窗口里组合化跑不赢缓慢增长单打」。

对照口径(与 Exp-3 shared_pool 完全一致)
-----------------------------------------
- min_var3 (70/10/20): 单账户真回测(含全部成本) × {on_change, monthly}。
- slow_only (100/0/0): 同引擎跑一遍作真单账户基准 —— 兼作引擎一致性校验
  (应≈ Exp-4 单腿 slow standalone 14.11% / Sharpe 0.92)。
- Exp-2 估计: 读 Exp-4 已存的 legs_daily_returns_6_since2016.parquet, 用同一
  _combo_daily 按 70/10/20 月度再平衡合成 → _metrics(乐观上界)。
- 全部用同一 _metrics(CAGR/年化波动/MaxDD/Sharpe rf=0)直接可比。

用法(长任务, 后台跑)
  nohup rtk python backend/services/backtest/strategies/experiments/lynch/portfolio/run_portfolio_2016plus_exp3.py \
      > logs/lynch_2016plus_exp3.log 2>&1 &
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
log = logging.getLogger("lynch_2016plus_exp3")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.portfolio.lynch_meta_combo_strategy import (
    LynchMetaComboStrategy,
)
# 复用 Exp-3 已验证的同口径件(策略腿配置 / 指标 / 曲线合成 / 基准 / 格式化)
from services.backtest.strategies.experiments.lynch.portfolio.run_portfolio_shared_pool import (
    LEG_CONFIGS,
    _metrics,
    _combo_daily,
    _csi300_daily_returns,
    _pct,
)

OUT_DIR = Path(__file__).resolve().parent
WINDOW = ("2016-01-01", "2026-06-01")  # 诚实成熟窗口, FRESH(iter 从 2016 起新跑)
MODES = ["on_change", "monthly"]

# 待验证的两组权重(顺序对齐 LEG_CONFIGS = slow/turn/asset)
WEIGHT_SETS = {
    "min_var3_70_10_20": {"slow_growers": 0.70, "turnarounds": 0.10, "asset_plays": 0.20},
    "slow_only_100": {"slow_growers": 1.0, "turnarounds": 0.0, "asset_plays": 0.0},
}


def _run_pool_w(sliced, mode: str, weights: dict) -> dict:
    """单账户真回测一次(指定权重)。逻辑与 shared_pool._run_pool 逐字一致, 仅权重参数化。"""
    legs = [(name, cls(param_overrides=ov)) for name, cls, ov in LEG_CONFIGS]
    meta = LynchMetaComboStrategy(legs=legs, weights=weights, rebalance_mode=mode)
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
        return {"cagr": None, "n_days": 0}
    dates = pd.to_datetime([p["date"] for p in ec])
    vals = pd.Series([float(p["total_value"]) for p in ec], index=dates).sort_index()
    daily = vals.pct_change().dropna()

    raw = res.get("raw_trades", []) or []
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
        "n_trades": len(raw),
        "total_cost": round(cost, 2),
        "cost_pct_of_final": (cost / final_val) if final_val else None,
        "final_value": round(final_val, 2),
        "turnover_ann": turnover_ann,
    })
    return m


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)

    start, end = WINDOW
    log.info("==== window since2016 (%s → %s) FRESH ====", start, end)
    sliced = data_cache.slice_bundle(bundle, None, start, end)

    report = {"window": [start, end], "note": "FRESH iter 从 2016 起", "sets": {}}

    # Exp-2 曲线级估计(读 Exp-4 的 6 腿 2016+ parquet)
    pq = OUT_DIR / "legs_daily_returns_6_since2016.parquet"
    exp2_est = {}
    if pq.exists():
        R = pd.read_parquet(pq)
        for sname, w in WEIGHT_SETS.items():
            cols = ["slow_growers", "turnarounds", "asset_plays"]
            wv = np.array([w[c] for c in cols], dtype=float)
            est = _metrics(_combo_daily(R[cols], wv))
            exp2_est[sname] = est
            log.info("[exp2/%s] CAGR=%s Sharpe=%.2f", sname,
                     _pct(est.get("cagr")), est.get("sharpe") or 0)
    else:
        log.warning("缺 %s, 跳过 Exp-2 估计", pq.name)

    # Exp-3 单账户真回测 × 权重 × mode
    for sname, w in WEIGHT_SETS.items():
        blk = {"weights": w, "exp2_estimate": exp2_est.get(sname, {}), "modes": {}}
        for mode in MODES:
            t1 = time.time()
            m = _run_pool_w(sliced, mode, w)
            blk["modes"][mode] = m
            log.info("[%s/%s] %.1fs trades=%s turnover=%.2f CAGR=%s Sharpe=%.2f MaxDD=%s cost=%s",
                     sname, mode, time.time() - t1, m.get("n_trades"),
                     m.get("turnover_ann") or 0, _pct(m.get("cagr")),
                     m.get("sharpe") or 0, _pct(m.get("max_drawdown")),
                     _pct(m.get("cost_pct_of_final")))
        report["sets"][sname] = blk

    bench = _csi300_daily_returns(start, end)
    if bench is not None:
        report["csi300"] = _metrics(bench)

    (OUT_DIR / "portfolio_2016plus_exp3.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    _write_overview(report)
    log.info("ALL DONE -> portfolio_2016plus_exp3.json + portfolio_2016plus_exp3_overview.md")


def _write_overview(report):
    s, e = report["window"]
    lines = [
        "# 林奇组合 · 2016+ 最优组合单账户真回测 (Exp-4 补充)",
        "",
        f"> 窗口 since2016 ({s} → {e}, FRESH)。验证 Exp-4 曲线级搜出的 2016+ 最优稳健组合",
        "> **min_var3 = slow .70 / turn .10 / asset .20** 在真单账户(含全部成本)里能否守住",
        "> 相对**缓慢增长单打**那 0.01 Sharpe 优势。slow_only 同引擎跑作真单账户基准 + 一致性校验。",
        "> Exp-2 估计 = 曲线级混合(无成本, 乐观上界); Exp-3 = 单账户真回测(整手/现金池/佣金印花税滑点)。",
        "",
    ]
    for sname, blk in report["sets"].items():
        w = blk["weights"]
        wstr = f"slow {w['slow_growers']:.2f} / turn {w['turnarounds']:.2f} / asset {w['asset_plays']:.2f}"
        lines += [f"## {sname} ({wstr})", "",
                  "| 口径 | CAGR | 年化波动 | MaxDD | Sharpe | 笔数 | 年化换手 | 成本/终值 |",
                  "|---|---|---|---|---|---|---|---|"]
        est = blk.get("exp2_estimate")
        if est:
            lines.append(f"| Exp-2 估计(乐观) | {_pct(est.get('cagr'))} | {_pct(est.get('ann_vol'))} | "
                         f"{_pct(est.get('max_drawdown'))} | {(est.get('sharpe') or 0):.2f} | - | - | - |")
        for mode in MODES:
            m = blk["modes"].get(mode, {})
            if not m:
                continue
            lines.append(f"| Exp-3 {mode} | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'))} | "
                         f"{_pct(m.get('max_drawdown'))} | {(m.get('sharpe') or 0):.2f} | "
                         f"{m.get('n_trades', '-')} | {(m.get('turnover_ann') or 0):.2f} | "
                         f"{_pct(m.get('cost_pct_of_final'))} |")
        lines.append("")

    bench = report.get("csi300")
    if bench:
        lines += ["## 基准", "",
                  "| 口径 | CAGR | 年化波动 | MaxDD | Sharpe |", "|---|---|---|---|---|",
                  f"| CSI300 | {_pct(bench.get('cagr'))} | {_pct(bench.get('ann_vol'))} | "
                  f"{_pct(bench.get('max_drawdown'))} | {(bench.get('sharpe') or 0):.2f} |", ""]

    (OUT_DIR / "portfolio_2016plus_exp3_overview.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
